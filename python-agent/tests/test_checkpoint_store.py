"""Offline routing checks and opt-in real Redis recovery, without model calls.

EASYJOB_CHECKPOINT_REDIS_TEST=1 python -m unittest discover -s tests -p test_checkpoint_store.py -v
Redis fixtures use unique checkpointqa_* threads; no flushes or production-key deletion.
"""
import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from redis.asyncio import Redis

from app.config import settings
from app.services.checkpoint_store import LatestRunRedisSaver, ScopedShallowRedisSaver
from app.services.checkpoint_retention import EXPIRED_CHECKPOINT_SQL, retention_parameters


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def saver(self, *, shallow_exists=False, legacy_root=None):
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver)
        BaseCheckpointSaver.__init__(saver)
        from collections import OrderedDict
        saver._routes = OrderedDict()
        saver.client = SimpleNamespace(exists=AsyncMock(return_value=shallow_exists))
        saver.latest = SimpleNamespace(_make_shallow_redis_checkpoint_key=lambda tid, ns: f'checkpoint:{tid}:{ns}')
        saver.legacy = SimpleNamespace(aget_tuple=AsyncMock(return_value=legacy_root))
        return saver

    async def test_new_run_and_child_namespace_use_latest(self):
        saver = self.saver()
        self.assertIs(await saver._backend({'configurable': {'thread_id': 'r'}}), saver.latest)
        self.assertIs(await saver._backend({'configurable': {'thread_id': 'r', 'checkpoint_ns': 'writing:task'}}), saver.latest)
        saver.legacy.aget_tuple.assert_awaited_once_with({'configurable': {'thread_id': 'r', 'checkpoint_ns': ''}})

    async def test_legacy_run_is_not_reinterpreted_as_shallow(self):
        saver = self.saver(legacy_root=object())
        self.assertIs(await saver._backend({'configurable': {'thread_id': 'old', 'checkpoint_ns': 'child'}}), saver.legacy)

    async def test_existing_shallow_root_survives_process_restart(self):
        saver = self.saver(shallow_exists=True)
        self.assertIs(await saver._backend({'configurable': {'thread_id': 'new'}}), saver.latest)
        saver.legacy.aget_tuple.assert_not_awaited()

    async def test_routing_cache_is_bounded(self):
        saver = self.saver()
        for n in range(300):
            await saver._backend({'configurable': {'thread_id': str(n)}})
        self.assertEqual(len(saver._routes), 256)

    async def test_pending_writes_are_scoped_and_read_failure_propagates(self):
        saver = ScopedShallowRedisSaver.__new__(ScopedShallowRedisSaver)
        BaseCheckpointSaver.__init__(saver)
        kind, blob = saver.serde.dumps_typed('valid')
        def write(cp, *, tid='run', ns='', channel='result'):
            return dict(thread_id=tid, checkpoint_ns=ns, checkpoint_id=cp,
                        task_id=cp, idx=0, channel=channel, type=kind, blob=saver._encode_blob(blob))
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=[write('old', channel='__error__'), write('current'),
                                                   write('current', tid='foreign'), write('current', ns='child')])
        saver._redis = SimpleNamespace(zrange=AsyncMock(return_value=['a', 'b', 'c', 'd']), pipeline=lambda **kw: pipeline)
        self.assertEqual(await saver._aload_pending_writes('run', '', 'current'), [('current', 'result', 'valid')])
        pipeline.execute.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await saver._aload_pending_writes('run', '', 'current')

    def test_retention_has_separate_budgets_and_excludes_live_runs(self):
        with patch.object(settings, 'CHECKPOINT_SUCCESS_RETENTION_DAYS', 1), patch.object(settings, 'CHECKPOINT_RETENTION_DAYS', 7):
            self.assertEqual(retention_parameters(), {'success_days': 1, 'failure_days': 7})
        self.assertIn("('succeeded','failed','cancelled','expired')", EXPIRED_CHECKPOINT_SQL)
        self.assertNotIn('awaiting_approval', EXPIRED_CHECKPOINT_SQL)

    async def test_resumed_run_can_enqueue_a_new_cleanup_generation(self):
        from app.services.operations import Operations
        generation = 'first-terminal-time'
        async def fetch(query, *args):
            if 'AS cleanup_key' in query:
                self.assertIn("DATE_FORMAT(r.updated_at", query)
                return [SimpleNamespace(_mapping={'run_id': 'r', 'user_id': 7, 'conversation_id': 11,
                        'cleanup_key': 'checkpoint-cleanup:r:' + generation})]
            return []
        database = SimpleNamespace(fetch_all=AsyncMock(side_effect=fetch), execute=AsyncMock())
        with patch('app.services.draft_commit.reconcile', AsyncMock()), \
             patch('app.rpc.blog_client.maintenance', AsyncMock(return_value={})), \
             patch('app.services.durable_jobs.DurableJobs.enqueue', AsyncMock()) as enqueue:
            await Operations(database).cleanup()
            generation = 'second-terminal-time'
            await Operations(database).cleanup()
        self.assertEqual([call.args[0] for call in enqueue.await_args_list],
                         ['checkpoint-cleanup:r:first-terminal-time', 'checkpoint-cleanup:r:second-terminal-time'])


class SimpleState(TypedDict):
    text: str
    saved: bool
    n: int


@unittest.skipUnless(os.getenv('EASYJOB_CHECKPOINT_REDIS_TEST') == '1', 'requires isolated real Redis thread fixtures')
class RedisRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_draft_gap_survives_restart_without_repeating_generation_or_review(self):
        from test_draft_recovery import DraftRecoveryTests
        async def reopen():
            await self.restart()
            return self.store
        generate, review, retrieval, repair, _ = await DraftRecoveryTests.execute(self,
            checkpoint='review', store=self.store, graph_config=self.config(), restart_store=reopen)
        self.assertEqual((generate.await_count, review.await_count, retrieval.await_count, repair.ainvoke.await_count), (1, 2, 1, 1))

    async def asyncSetUp(self):
        self.client = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT,
                            db=settings.REDIS_STACK_DB, password=settings.REDIS_STACK_PASSWORD or None,
                            socket_connect_timeout=3, socket_timeout=10)
        await self.client.ping()
        self.threads = []
        self.store = await LatestRunRedisSaver(redis_client=self.client).__aenter__()

    def config(self):
        tid = 'checkpointqa_' + uuid4().hex
        self.threads.append(tid)
        return {'configurable': {'thread_id': tid}}

    async def restart(self):
        await self.store.__aexit__(None, None, None)
        self.store = await LatestRunRedisSaver(redis_client=self.client).__aenter__()

    async def asyncTearDown(self):
        try:
            for tid in self.threads:
                await self.store.adelete_thread(tid)
                for prefix in ('checkpoint', 'checkpoint_write', 'checkpoint_latest', 'write_keys_zset'):
                    remaining = [k async for k in self.client.scan_iter(match=f'{prefix}:{tid}:*', count=1000)]
                    self.assertEqual(remaining, [], 'all fixture namespace keys and writes must be removed')
        finally:
            await self.store.__aexit__(None, None, None)
            await self.client.aclose()

    def writing(self, counts):
        def generate(s):
            counts['generate'] += 1
            return {'text': 'draft content'}
        def approve(s):
            decision = interrupt({'draft': s['text']})
            return {'text': s['text'] + (' revised' if decision == 'revise' else '')}
        def save(s):
            counts['save'] += 1
            return {'saved': True}
        child = StateGraph(SimpleState)
        child.add_node('generate', generate); child.add_node('approve', approve); child.add_node('save', save)
        child.add_edge(START, 'generate'); child.add_edge('generate', 'approve')
        child.add_edge('approve', 'save'); child.add_edge('save', END)
        parent = StateGraph(SimpleState)
        parent.add_node('writing', child.compile()); parent.add_edge(START, 'writing'); parent.add_edge('writing', END)
        return parent

    async def test_nested_approval_survives_restart_without_regeneration(self):
        cfg = self.config(); counts = {'generate': 0, 'save': 0}
        graph = self.writing(counts).compile(checkpointer=self.store)
        await graph.ainvoke({'text': '', 'saved': False}, cfg)
        before = await graph.aget_state(cfg, subgraphs=True)
        self.assertTrue(before.tasks[0].interrupts)
        self.assertEqual(counts, {'generate': 1, 'save': 0})
        await self.restart()
        graph = self.writing(counts).compile(checkpointer=self.store)
        output = await graph.ainvoke(Command(resume='approve'), cfg)
        self.assertTrue(output['saved'])
        self.assertEqual(counts, {'generate': 1, 'save': 1})
        self.assertEqual((await graph.aget_state(cfg)).next, ())

    async def test_legacy_nested_approval_uses_old_format_after_upgrade(self):
        cfg = self.config(); counts = {'generate': 0, 'save': 0}
        graph = self.writing(counts).compile(checkpointer=self.store.legacy)
        await graph.ainvoke({'text': '', 'saved': False}, cfg)
        await self.restart()
        self.assertIs(await self.store._backend(cfg), self.store.legacy)
        graph = self.writing(counts).compile(checkpointer=self.store)
        self.assertTrue((await graph.ainvoke(Command(resume='approve'), cfg))['saved'])
        self.assertEqual(counts, {'generate': 1, 'save': 1})

    async def test_native_parallel_branch_failure_preserves_successful_pending_write(self):
        class ParallelState(TypedDict):
            results: Annotated[dict, lambda a, b: {**a, **b}]
        cfg = self.config(); calls = {'a': 0, 'b': 0, 'join': 0}; a_done = asyncio.Event()
        async def a(state):
            calls['a'] += 1; a_done.set(); return {'results': {'a': 'A'}}
        async def b(state):
            calls['b'] += 1
            await a_done.wait()
            if calls['b'] == 1:
                await asyncio.sleep(.05)
                raise TimeoutError('injected network timeout')
            return {'results': {'b': 'B'}}
        def join(state):
            self.assertEqual(state['results'], {'a': 'A', 'b': 'B'}); calls['join'] += 1; return {}
        def graph():
            g = StateGraph(ParallelState)
            g.add_node('a', a); g.add_node('b', b); g.add_node('join', join)
            g.add_edge(START, 'a'); g.add_edge(START, 'b'); g.add_edge(['a', 'b'], 'join'); g.add_edge('join', END)
            return g.compile(checkpointer=self.store)
        with self.assertRaises(TimeoutError): await graph().ainvoke({'results': {}}, cfg)
        self.assertEqual(calls['join'], 0)
        await self.restart()
        await graph().ainvoke(None, cfg)
        self.assertEqual(calls, {'a': 1, 'b': 2, 'join': 1})

    async def test_production_delegate_recovers_committed_artifact(self):
        # The production test cancels inside main_delegate, before its state is
        # checkpointed. Its task artifact ledger must supply the finished parent.
        import test_agent_optimizations as cases
        case = cases.ArtifactTests()
        case.redis_checkpointer = self.store
        case.redis_thread = self.config()['configurable']['thread_id']
        await case.test_checkpoint_restart_reuses_finished_parent_and_reruns_unfinished_child()

    async def test_production_parallel_dag_and_draft_approval(self):
        import test_staged_agent as cases
        case = cases.GraphExecutionTests()
        case.redis_checkpointer = self.store
        case.redis_thread = self.config()['configurable']['thread_id']
        # Keep only model/API boundaries stubbed, exactly as in the routing suite.
        with patch('app.services.grounding.review_text', AsyncMock(return_value=[])), \
             patch('app.services.grounding.repair_text', AsyncMock(side_effect=TimeoutError('offline auditor'))):
            await case.test_actual_graph_parallel_dependencies_and_approval()

    async def run_writing_case(self, method):
        import test_phase0 as cases
        case = cases.WritingTests()
        case.redis_checkpointer = self.store
        case.redis_thread = self.config()['configurable']['thread_id']
        await case.asyncSetUp()
        try:
            await getattr(case, method)()
        finally:
            case.doCleanups()

    async def test_production_revision_requires_another_approval(self):
        await self.run_writing_case('test_revision_requires_a_second_approval')

    async def test_production_rejection_does_not_save(self):
        await self.run_writing_case('test_reject_does_not_save')

    async def test_snapshot_count_and_memory_are_bounded_by_namespace(self):
        def loop_graph(saver):
            g = StateGraph(SimpleState)
            g.add_node('step', lambda s: {'n': s['n'] + 1})
            g.add_edge(START, 'step'); g.add_conditional_edges('step', lambda s: 'step' if s['n'] < 12 else END)
            return g.compile(checkpointer=saver)
        report = {}
        for name, saver in [('full', self.store.legacy), ('latest', self.store)]:
            cfg = self.config(); tid = cfg['configurable']['thread_id']
            await loop_graph(saver).ainvoke({'n': 0, 'text': '合成检索资料' * 7000}, cfg)
            keys = [k async for k in self.client.scan_iter(match=f'checkpoint:{tid}:*', count=1000)]
            all_keys = set(keys)
            for prefix in ('checkpoint_write', 'checkpoint_latest', 'write_keys_zset'):
                all_keys.update([k async for k in self.client.scan_iter(match=f'{prefix}:{tid}:*', count=1000)])
            pipe = self.client.pipeline(transaction=False)
            for key in all_keys: pipe.memory_usage(key)
            total = sum(size or 0 for size in await pipe.execute())
            report[name] = {'snapshots': len(keys), 'snapshot_bytes': sum([await self.client.memory_usage(k) for k in keys]),
                            'all_run_keys': len(all_keys), 'all_run_bytes': total}
            self.assertEqual((await loop_graph(saver).aget_state(cfg)).values['n'], 12)
        self.assertEqual(report['latest']['snapshots'], 1)
        self.assertGreater(report['full']['snapshots'], 10)
        self.assertLess(report['latest']['snapshot_bytes'], report['full']['snapshot_bytes'] / 5)
        output = Path(__file__).resolve().parents[2] / 'logs/checkpoint-storage-comparison.json'
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
