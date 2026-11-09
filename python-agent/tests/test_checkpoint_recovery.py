"""Offline recovery contracts: actual pending work, side effects and fencing."""
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from app.services.run_service import RunService
from app.services.run_repository import RunRepository
from app.services.checkpoint_store import LatestRunRedisSaver, checkpoint_writer
from app.graph.staged_runtime import guard_node


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    def setup_case(self, node='main_agent', **values):
        self.run = dict(run_id='r', user_id=7, conversation_id=11, status='failed', result_json='{}', execution_token='old')
        self.repo = SimpleNamespace(has_memory_write=AsyncMock(return_value=False))
        self.memory = SimpleNamespace(load_context=AsyncMock(return_value={'user_profile': {}, 'active_constraints': []}))
        self.service = RunService(SimpleNamespace(), self.memory, repository=self.repo)
        self.snapshot = SimpleNamespace(next=(node,), tasks=[], values={
            'run_id': 'r', 'user_id': 7, 'conversation_id': 11, **values})
        self.graph = SimpleNamespace(aget_state=AsyncMock(return_value=self.snapshot))

    async def test_snapshot_is_authority_even_with_no_or_stale_ledger_node(self):
        self.setup_case(main_round=3)
        self.assertIs(await self.service.recovery_snapshot(self.run, self.graph), self.snapshot)
        self.repo.has_memory_write.assert_awaited_once_with('r')

    async def test_end_write_approval_and_incompatible_checkpoint_fail_closed(self):
        for pending in [(), ('prepare_draft',), ('main_agent', 'execute_tool')]:
            self.setup_case(); self.snapshot.next = pending
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))
        self.setup_case(); self.snapshot.tasks = [SimpleNamespace(interrupts=[object()])]
        self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))
        self.setup_case(); self.graph.aget_state.side_effect = ValueError('old schema')
        self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_committed_memory_without_checkpoint_output_is_not_replayed(self):
        self.setup_case(); self.repo.has_memory_write.return_value = True
        self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_private_snapshots_and_changed_constraints_are_not_reused(self):
        for state in [{'editor_context': {'snapshot_id': 'old'}}, {'memory_changes_queued': True},
                      {'task_results': {'a': {'retrieval_target': 'drafts'}}},
                      {'user_profile': {}, 'active_constraints': [{'id': 'old'}]}]:
            self.setup_case(**state)
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))
        self.setup_case(user_profile={}, active_constraints=[])
        self.assertIsNotNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_public_evidence_must_still_be_visible_and_current(self):
        self.setup_case(citations=[{'articleId': '1', 'sourceHash': 'old'}])
        with patch('app.services.checkpoint_recovery.verify_public_evidence', AsyncMock(side_effect=ValueError('changed'))) as verify:
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))
        verify.assert_awaited_once()

    async def test_only_registered_public_read_tool_can_resume(self):
        from app.graph.staged_plan import ExecutionTask
        task = ExecutionTask(task_id='a', actor='main', kind='search', instruction='lookup')
        self.setup_case('execute_tool', plan={'tasks': [task.model_dump()]})
        self.assertIsNotNone(await self.service.recovery_snapshot(self.run, self.graph))
        self.snapshot.values['plan']['tasks'][0]['retrieval_target'] = 'drafts'
        self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_active_run_only_reconnects_without_claim_or_replaying_graph(self):
        self.setup_case(); self.run['status'] = 'running'; self.run['execution_token'] = 'live'
        self.repo.get = AsyncMock(return_value=self.run); self.repo.expire_existing = AsyncMock()
        self.repo.claim_recovery = AsyncMock()
        self.service.conversations = SimpleNamespace(require_owner=AsyncMock())
        _, config = await self.service.prepare_recovery('r', 7, self.graph, 'unused')
        self.assertTrue(config['configurable']['reconnect'])
        self.repo.claim_recovery.assert_not_awaited(); self.graph.aget_state.assert_not_awaited()

    def test_draft_commit_intent_blocks_recovery_before_any_checkpoint_read(self):
        self.setup_case()
        self.run['result_json'] = '{"draft_commit": {"id": "accepted"}}'
        self.assertFalse(self.service.recovery_candidate(self.run))

    async def test_missing_identity_unversioned_evidence_and_unverifiable_queries_are_rejected(self):
        cases = [{'run_id': None}, {'conversation_id': 99}, {'citations': [{'articleId': '1'}]},
                 {'task_results': {'q': {'status': 'succeeded', 'tool_name': 'get_article_comments'}}},
                 {'task_results': {'web': {'citations': [{'url': 'https://example.com'}],
                    'source_run_updated_at': '2020-01-01T00:00:00Z'}}}]
        for values in cases:
            self.setup_case(**values)
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_old_web_in_delivery_and_previous_results_is_not_refreshed(self):
        old = {'citations': [{'url': 'https://example.com'}], 'source_run_updated_at': '2020-01-01T00:00:00Z'}
        for values in [{'delivery_evidence': old}, {'previous_run': {'reusable_results': {'old': old}}}]:
            self.setup_case(**values); self.run['created_at'] = '2020-01-01T00:00:00Z'
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))

    async def test_cancelled_and_saved_draft_snapshots_are_not_recovered(self):
        for values in [{'cancelled': True}, {'draft_article_id': 1}, {'draft_document': {'text': 'draft'}}]:
            self.setup_case(**values)
            self.assertIsNone(await self.service.recovery_snapshot(self.run, self.graph))


class FencingTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_double_click_claims_once(self):
        lock = asyncio.Lock()
        run = dict(run_id='r', user_id=7, conversation_id=11, status='failed', result_json='{}', recovery_count=0)
        @asynccontextmanager
        async def transaction():
            async with lock: yield
        async def execute(sql, params):
            run.update(status='running', execution_token=params['token'], recovery_count=1)
        db = SimpleNamespace(transaction=transaction,
            fetch_one=AsyncMock(side_effect=lambda *args: SimpleNamespace(_mapping=dict(run))),
            fetch_val=AsyncMock(return_value=None), execute=AsyncMock(side_effect=execute))
        repo = RunRepository(db)
        with patch.object(repo, '_lock_conversation', AsyncMock()), \
                patch.object(repo, 'latest', AsyncMock(return_value={'run_id': 'r'})), \
                patch.object(repo, 'get', AsyncMock(side_effect=lambda *args: dict(run))):
            outcomes = await asyncio.gather(repo.claim_recovery(11, 7, 'r'), repo.claim_recovery(11, 7, 'r'), return_exceptions=True)
        self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, HTTPException) for value in outcomes), 1)
        db.execute.assert_awaited_once()

    async def test_http_active_reconnect_skips_admission_and_graph(self):
        from app import main
        from app.security.principal import Principal
        service = SimpleNamespace(reconnect_config=AsyncMock(return_value={'configurable': {'execution_token': 'live'}}))
        admission = SimpleNamespace(acquire=AsyncMock())
        with patch.object(main, 'run_service', service), patch.object(main, 'execution_admission', admission), \
                patch.object(main, 'get_graph', AsyncMock()) as graph, \
                patch.object(main.stream_delivery, 'follow', return_value=iter(())):
            response = await main.recover_run('r', Principal(user_id=7))
        self.assertEqual(response.status_code, 200)
        admission.acquire.assert_not_awaited(); graph.assert_not_awaited()

    async def test_none_resume_keeps_completed_retrieval_with_real_saver_wrapper(self):
        seen = []; generations = []; main_attempts = 0
        @asynccontextmanager
        async def writer(rid, token):
            generations.append(token); yield
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver); BaseCheckpointSaver.__init__(saver)
        backend = InMemorySaver(); saver.legacy = backend
        saver._backend = AsyncMock(return_value=backend)
        async def retrieve(state):
            seen.append('retrieve'); return {**state, 'evidence': 'retained'}
        async def main(state):
            nonlocal main_attempts
            main_attempts += 1
            if main_attempts == 1:
                raise ConnectionError('simulated interrupted Main connection')
            seen.append(state['evidence']); return state
        builder = StateGraph(dict)
        builder.add_node('main_retrieve', retrieve); builder.add_node('main_agent', main)
        builder.add_edge(START, 'main_retrieve'); builder.add_edge('main_retrieve', 'main_agent')
        builder.add_edge('main_agent', END)
        graph = builder.compile(checkpointer=saver)
        config = {'configurable': {'thread_id': 'run_r', 'run_id': 'r', 'execution_token': 'old'}}
        with patch('app.services.run_repository.run_repository', SimpleNamespace(checkpoint_writer=writer)):
            with self.assertRaises(ConnectionError):
                await graph.ainvoke({'run_id': 'r'}, config)
            self.assertEqual((await graph.aget_state(config)).next, ('main_agent',))
            generations.clear(); config['configurable']['execution_token'] = 'new'
            await graph.ainvoke(None, config)
        self.assertEqual(seen, ['retrieve', 'retained'])
        self.assertEqual(main_attempts, 2)
        self.assertTrue(generations)
        self.assertEqual(set(generations), {'new'})

    async def test_hung_redis_write_releases_generation_lock(self):
        released = asyncio.Event()
        @asynccontextmanager
        async def writer(rid, token):
            try: yield
            finally: released.set()
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver); BaseCheckpointSaver.__init__(saver)
        async def hang(*args): await asyncio.Event().wait()
        saver._backend = AsyncMock(return_value=SimpleNamespace(aput=hang))
        config = {'configurable': {'thread_id': 'run_r', 'run_id': 'r', 'execution_token': 'new'}}
        with patch('app.services.run_repository.run_repository', SimpleNamespace(checkpoint_writer=writer)), \
                patch('app.services.checkpoint_store.CHECKPOINT_WRITE_TIMEOUT_SECONDS', .01):
            with self.assertRaises(TimeoutError): await saver.aput(config, {}, {}, {})
        self.assertTrue(released.is_set())

    async def test_resumed_main_memory_enqueue_receives_new_token(self):
        from app.graph import staged_runtime as runtime
        received = []
        async def main_node(state):
            # Same state argument consumed by memory_policy.enqueue_changes.
            received.append(state['execution_token'])
            return {'execution_token': state['execution_token']}
        graph = StateGraph(dict)
        graph.add_node('main_agent', guard_node('main_agent', main_node))
        graph.add_edge(START, 'main_agent'); graph.add_edge('main_agent', END)
        compiled = graph.compile(checkpointer=InMemorySaver(), interrupt_before=['main_agent'])
        cfg = {'configurable': {'thread_id': 'offline', 'execution_token': 'old'}}
        with patch.object(runtime, 'assert_run', AsyncMock()), patch.object(runtime, 'node_activity', AsyncMock()):
            await compiled.ainvoke({'execution_token': 'old'}, cfg)
            cfg['configurable']['execution_token'] = 'new'
            await compiled.ainvoke(None, cfg)
        self.assertEqual(received, ['new'])

    async def test_delayed_old_checkpoint_cannot_write_after_claim_and_new_tail_writes_survive(self):
        token = 'old'; status = 'failed'; lock = asyncio.Lock()
        @asynccontextmanager
        async def transaction():
            async with lock: yield
        async def fetch(*args):
            return SimpleNamespace(_mapping={'execution_token': token, 'status': status})
        repo = RunRepository(SimpleNamespace(transaction=transaction, fetch_one=AsyncMock(side_effect=fetch)))
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver); BaseCheckpointSaver.__init__(saver)
        backend = SimpleNamespace(aput=AsyncMock(), aput_writes=AsyncMock())
        saver._backend = AsyncMock(return_value=backend)
        config = {'configurable': {'thread_id': 'run_r', 'run_id': 'r', 'execution_token': 'old', 'checkpoint_ns': 'child'}}
        async with lock:
            with patch('app.services.run_repository.run_repository', repo):
                delayed = asyncio.create_task(saver.aput(config, {}, {}, {}))
                await asyncio.sleep(0)
                token = 'new'; status = 'running'
        with self.assertRaises(HTTPException): await delayed
        with patch('app.services.run_repository.run_repository', repo):
            with self.assertRaises(HTTPException): await saver.aput_writes(config, [], 'task')
            config['configurable']['execution_token'] = 'new'; status = 'awaiting_approval'
            await saver.aput(config, {}, {}, {})
            await saver.aput_writes(config, [], 'task')
        backend.aput.assert_awaited_once(); backend.aput_writes.assert_awaited_once()

    async def test_business_thread_cannot_silently_bypass_fence(self):
        with self.assertRaises(ValueError):
            async with checkpoint_writer({'configurable': {'thread_id': 'run_r'}}): pass
        async with checkpoint_writer({'configurable': {'thread_id': 'offline-test'}}): pass
        with self.assertRaises(ValueError):
            async with checkpoint_writer({'configurable': {'thread_id': 'run_other', 'run_id': 'r', 'execution_token': 'new'}}): pass

    async def test_parent_and_child_graph_checkpoint_writes_inherit_run_identity(self):
        seen = []
        @asynccontextmanager
        async def writer(rid, token):
            seen.append((rid, token)); yield
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver); BaseCheckpointSaver.__init__(saver)
        backend = InMemorySaver()
        saver.legacy = backend
        saver._backend = AsyncMock(return_value=backend)
        child = StateGraph(dict)
        child.add_node('step', lambda state: state)
        child.add_edge(START, 'step'); child.add_edge('step', END)
        parent = StateGraph(dict)
        parent.add_node('child', child.compile())
        parent.add_edge(START, 'child'); parent.add_edge('child', END)
        graph = parent.compile(checkpointer=saver)
        config = {'configurable': {'thread_id': 'run_r', 'run_id': 'r', 'execution_token': 'new'}}
        with patch('app.services.run_repository.run_repository', SimpleNamespace(checkpoint_writer=writer)):
            await graph.ainvoke({'value': 1}, config)
            snapshot = await graph.aget_state(config)
        self.assertFalse(snapshot.next)
        self.assertGreater(len(seen), 4)
        self.assertTrue(all(identity == ('r', 'new') for identity in seen))
        namespaces = [call.args[0]['configurable'].get('checkpoint_ns', '') for call in saver._backend.await_args_list]
        self.assertTrue(any(ns.startswith('child:') for ns in namespaces))
