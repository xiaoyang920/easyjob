"""Optimization invariants, measured without cloud calls or production mutations."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from pydantic import ValidationError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from app.graph import action_runtime as actions, staged_runtime as runtime
from app.graph.state import AgentState
from app.graph.state_factory import create_initial_state
from app.graph.staged_plan import ExecutionTask, DelegatedTask, DependencyPlan, compile_delegate_task
from app.graph.main_agent import RetrievalRequest
from app.services.query_rewrite import QueryRewriteService
from app.services.query_vector_cache import QueryVectorCache
from app.services.stream_coalescing import coalesce_previews, preview_delta
from app.services.task_artifacts import TaskArtifacts, task_fingerprint
from app.services.run_service import RunService
from app.services.run_repository import RunRepository
from app.services.run_metrics import RunMetrics, metrics_from
from app import main
from app.security.principal import Principal
from app import migrate
import httpx


def preview(text, kind='delta'):
    return 'data:__PREVIEW__:' + json.dumps({'type': kind, 'content': text, 'provisional': True}, ensure_ascii=False) + '\n\n'


class QueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_query_skips_model_and_preserves_author_time_tag_filters(self):
        service = QueryRewriteService.__new__(QueryRewriteService)
        service.rewrite = AsyncMock()
        task = {'instruction': '找小王这个月的 Redis 文', 'search_query': 'Redis 缓存一致性',
                'filters': {'author_name': '小王', 'time_range': 'month', 'required_tags': ['Redis']}}
        result = await service.rewrite_request(task, task['instruction'], [])
        self.assertEqual(result['semantic_queries'], ['Redis 缓存一致性'])
        self.assertEqual(result['filters'].author_name, '小王')
        self.assertEqual(result['filters'].required_tags, ['Redis'])
        self.assertEqual(result['filters'].time_range, 'month')
        service.rewrite.assert_not_awaited()

    async def test_unresolved_filters_references_and_feedback_use_rewrite(self):
        service = QueryRewriteService.__new__(QueryRewriteService)
        service.rewrite = AsyncMock(return_value={'status': 'rewritten'})
        cases = [({'instruction': 'q', 'search_query': 'Redis'}, 'q'),
                 ({'instruction': 'q', 'search_query': '它的缓存', 'filters': {}}, 'q'),
                 ({'instruction': 'q', 'search_query': 'Redis', 'filters': {}}, 'q\n修正策略')]
        for task, query in cases:
            self.assertEqual(await service.rewrite_request(task, query, []), {'status': 'rewritten'})
        self.assertEqual(service.rewrite.await_count, 3)

    def test_query_is_not_allowed_to_memory_or_analysis(self):
        for construct, kwargs in [(RetrievalRequest, {'instruction': 'q', 'target': 'memory'}),
                                 (DelegatedTask, {'task_id': 'a', 'instruction': 'q', 'subagent': 'analysis'}),
                                 (ExecutionTask, {'task_id': 'a', 'instruction': 'q', 'kind': 'analysis', 'actor': 'subagent'})]:
            with self.assertRaises(ValidationError):
                construct(**kwargs, search_query='Redis')


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_queries_share_call_but_vectors_are_independent(self):
        cache = QueryVectorCache()
        async def provider():
            await asyncio.sleep(.01)
            return [1., 2.]
        operation = AsyncMock(side_effect=provider)
        vectors = await asyncio.gather(*(cache.get_or_compute('model:a', 'q', 2, operation) for _ in range(20)))
        operation.assert_awaited_once()
        vectors[0][0] = 99
        self.assertEqual(await cache.get_or_compute('model:a', 'q', 2, operation), [1., 2.])
        self.assertEqual(cache.coalesced, 19)
        self.assertEqual(cache.hits, 1)
        self.assertNotIn('q', cache.values)

    async def test_expiry_namespace_and_lru_do_not_return_old_model_vectors(self):
        now = [0.]
        cache = QueryVectorCache(capacity=2, ttl=10, clock=lambda: now[0])
        operation = AsyncMock(return_value=[1.])
        await cache.get_or_compute('model:a', 'q', 1, operation)
        await cache.get_or_compute('model:b', 'q', 1, operation)
        now[0] = 11.
        await cache.get_or_compute('model:a', 'q', 1, operation)
        await cache.get_or_compute('model:a', 'next', 1, operation)
        await cache.get_or_compute('model:b', 'q', 1, operation)
        self.assertEqual(operation.await_count, 5)
        self.assertEqual(len(cache.values), 2)

    async def test_cancelled_waiter_does_not_cancel_shared_provider(self):
        ready, release = asyncio.Event(), asyncio.Event()
        async def provider():
            ready.set()
            await release.wait()
            return [1.]
        cache = QueryVectorCache()
        waiter = asyncio.create_task(cache.get_or_compute('a', 'q', 1, provider))
        await ready.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError): await waiter
        second = asyncio.create_task(cache.get_or_compute('a', 'q', 1, provider))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await second, [1.])
        self.assertEqual(cache.misses, 1)

    async def test_provider_failure_is_not_cached(self):
        cache = QueryVectorCache()
        operation = AsyncMock(side_effect=[RuntimeError('temporary'), [1.]])
        with self.assertRaises(RuntimeError): await cache.get_or_compute('a', 'q', 1, operation)
        self.assertEqual(await cache.get_or_compute('a', 'q', 1, operation), [1.])
        self.assertEqual(operation.await_count, 2)

    async def test_invalid_vectors_and_disabled_or_long_queries_are_never_cached(self):
        for vector in ([float('nan')], [True], [1., 2.]):
            cache, op = QueryVectorCache(), AsyncMock(return_value=vector)
            for _ in range(2): await cache.get_or_compute('a', 'q', 1, op)
            self.assertEqual(op.await_count, 2)
        for cache, query in [(QueryVectorCache(capacity=0), 'q'), (QueryVectorCache(), 'x' * 4001)]:
            op = AsyncMock(return_value=[1.])
            for _ in range(2): await cache.get_or_compute('a', query, 1, op)
            self.assertEqual(op.await_count, 2)


class CoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_identity_and_barrier_order_are_preserved(self):
        frames = [preview('第一段'), preview('\n'), preview('中文😀'), 'data:__PROGRESS__:done\n\n',
                  preview('第二段'), preview('完成'), 'data:__ANSWER__:{"seq":0,"content":"最终"}\n\n',
                  preview('替换', 'replace'), 'data:[DONE]\n\n']
        async def source():
            for frame in frames: yield frame
        output = [frame async for frame in coalesce_previews(source())]
        self.assertEqual(output[0], frames[0])
        self.assertEqual(''.join(preview_delta(f)['content'] for f in output if preview_delta(f)), '第一段\n中文😀第二段完成')
        self.assertEqual([f for f in output if not preview_delta(f)], [f for f in frames if not preview_delta(f)])
        self.assertEqual(output[1], preview('\n中文😀'))
        self.assertLess(len(output), len(frames))

    async def test_first_text_immediate_pending_text_flushes_during_provider_pause(self):
        release = asyncio.Event()
        async def source():
            yield preview('first')
            yield preview('pending')
            await release.wait()
            yield 'data:[DONE]\n\n'
        stream = coalesce_previews(source(), interval=.01)
        self.assertEqual(await asyncio.wait_for(anext(stream), .2), preview('first'))
        self.assertEqual(await asyncio.wait_for(anext(stream), .2), preview('pending'))
        release.set()
        self.assertEqual(await anext(stream), 'data:[DONE]\n\n')
        await stream.aclose()

    async def test_close_cancels_pending_read_without_orphaning_generator(self):
        closed = asyncio.Event()
        async def source():
            try:
                yield preview('first')
                yield preview('pending')
                await asyncio.Event().wait()
            finally: closed.set()
        stream = coalesce_previews(source(), interval=.01)
        await anext(stream)
        await anext(stream)
        await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_size_limit_and_malformed_frame_are_barriers(self):
        async def source():
            for frame in [preview('a'), preview('123'), preview('456'), 'data:__PREVIEW__:invalid\n\n']:
                yield frame
        output = [f async for f in coalesce_previews(source(), max_chars=4)]
        self.assertEqual(output, [preview('a'), preview('123456'), 'data:__PREVIEW__:invalid\n\n'])


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        task = ExecutionTask(task_id='a', actor='subagent', kind='search', instruction='Redis')
        state = create_initial_state(7, 'research', [])
        state.update(run_id='run', execution_token='old', conversation_id=11)
        return runtime.task_context(state, task)

    def result(self):
        return {'task_id': 'a', 'actor': 'subagent', 'kind': 'search', 'status': 'succeeded',
                'result': 'Redis', 'citations': [], 'article_cards': []}

    async def test_same_run_owner_hash_and_source_version_are_checked(self):
        context = self.context()
        result = self.result()
        db = SimpleNamespace(fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping={
            'input_hash': task_fingerprint(context), 'result_json': json.dumps(result)})))
        verifier = AsyncMock()
        ledger = TaskArtifacts(db, verifier)
        self.assertEqual(await ledger.load(context, task_fingerprint(context)), result)
        self.assertEqual(db.fetch_one.call_args.args[1]['uid'], 7)
        self.assertEqual(db.fetch_one.call_args.args[1]['rid'], 'run')
        self.assertIsNone(await ledger.load(context, 'changed-input'))
        verifier.side_effect = ValueError('source changed')
        self.assertIsNone(await ledger.load(context, task_fingerprint(context)))

    def test_fingerprint_stable_across_execution_tokens_but_changes_with_input(self):
        context = self.context()
        original = task_fingerprint(context)
        self.assertEqual(original, task_fingerprint({**context, 'execution_token': 'new'}))
        for key, value in [('dependency_context', 'new evidence'), ('active_constraints', [{'id': 5}]),
                           ('current_task', {**context['current_task'], 'allow_web': True})]:
            self.assertNotEqual(original, task_fingerprint({**context, key: value}))

    async def test_failed_or_different_actor_results_are_not_reused(self):
        context = self.context()
        for update in [{'status': 'tool_error'}, {'actor': 'main'}, {'task_id': 'b'}]:
            db = SimpleNamespace(fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping={
                'input_hash': task_fingerprint(context), 'result_json': {**self.result(), **update}})))
            self.assertIsNone(await TaskArtifacts(db, AsyncMock()).load(context, task_fingerprint(context)))

    async def test_old_executor_cannot_commit_result(self):
        @asynccontextmanager
        async def transaction(): yield
        db = SimpleNamespace(transaction=transaction, fetch_val=AsyncMock(return_value=None), execute=AsyncMock())
        context = self.context()
        with self.assertRaises(HTTPException): await TaskArtifacts(db).save(context, 'hash', self.result(), 'old')
        db.execute.assert_not_awaited()

    async def test_checkpoint_restart_reuses_finished_parent_and_reruns_unfinished_child(self):
        # Cancel the actual delegate node after its first artifact commits. Parent
        # output is absent in the checkpoint; recovery must use the task ledger.
        tasks = [ExecutionTask(task_id='a', actor='subagent', kind='search', instruction='A'),
                 ExecutionTask(task_id='b', actor='subagent', kind='analysis', instruction='B', depends_on=['a'])]
        from app.graph.staged_plan import ExecutionPlan
        state = create_initial_state(7, 'research', [])
        state.update(run_id='run', execution_token='old', plan=ExecutionPlan(tasks=tasks).model_dump(), main_action='delegate', main_round=2)
        saved, calls, entered = {}, [], asyncio.Event()
        async def load(context, fingerprint): return saved.get((context['task_id'], fingerprint))
        async def save(context, fingerprint, result, token): saved[context['task_id'], fingerprint] = result
        async def worker(context):
            tid = context['task_id']
            calls.append(tid)
            if tid == 'b' and calls.count('b') == 1:
                entered.set()
                await asyncio.Event().wait()
            return {'task_results': {tid: {'task_id': tid, 'actor': 'subagent', 'kind': context['current_task']['kind'],
                    'status': 'succeeded', 'result': tid, 'citations': [], 'article_cards': []}}}
        graph = StateGraph(AgentState)
        graph.add_node('main_delegate', actions.main_delegate_node)
        graph.add_edge(START, 'main_delegate'); graph.add_edge('main_delegate', END)
        graph = graph.compile(checkpointer=InMemorySaver())
        config = {'configurable': {'thread_id': 'recovery', 'execution_token': 'old'}}
        with patch.object(actions, 'task_artifacts', SimpleNamespace(load=load, save=save)), \
             patch.object(runtime, 'assert_run', AsyncMock()), patch.object(runtime, 'subagent_node', worker), \
             patch.object(actions, 'activity', AsyncMock()):
            first = asyncio.create_task(graph.ainvoke(state, config))
            await asyncio.wait_for(entered.wait(), 2)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError): await first
            snapshot = await graph.aget_state(config)
            self.assertEqual(snapshot.next, ('main_delegate',))
            config['configurable']['execution_token'] = 'new'
            output = await graph.ainvoke(None, config)
        self.assertEqual(calls, ['a', 'b', 'b'])
        self.assertEqual(output['task_results']['b']['status'], 'succeeded')
        self.assertEqual(output['main_round'], 2)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def fixture_run(self, **update):
        return {'run_id': 'run', 'conversation_id': 11, 'user_id': 7, 'status': 'failed', 'draft_article_id': None,
                'execution_token': 'old', 'result_json': json.dumps({'recovery_node': 'main_delegate'}), **update}

    async def test_only_readonly_pending_delegate_can_be_recovered(self):
        service = RunService(SimpleNamespace(), SimpleNamespace())
        plan = {'tasks': [ExecutionTask(task_id='a', actor='subagent', kind='search', instruction='A').model_dump()]}
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(next=('main_delegate',), tasks=[], values={'plan': plan})))
        self.assertIsNotNone(await service.recovery_snapshot(self.fixture_run(), graph))
        for update in [{'status': 'cancelled'}, {'status': 'awaiting_approval'}, {'draft_article_id': 99}, {'recovery_count': 1}]:
            self.assertIsNone(await service.recovery_snapshot(self.fixture_run(**update), graph))
        graph.aget_state.return_value.next = ('main_writing',)
        self.assertIsNone(await service.recovery_snapshot(self.fixture_run(), graph))

    async def test_recovery_preserves_usage_and_binds_new_admission_token(self):
        run = self.fixture_run(result_json=json.dumps({'recovery_node': 'main_delegate', 'metrics': {'budget_charged_tokens': 1234, 'llm_calls': 2}}))
        repo = SimpleNamespace(get=AsyncMock(return_value=run), claim_recovery=AsyncMock(return_value={**run, 'execution_token': 'new'}),
                bind_admission=AsyncMock(), fail=AsyncMock())
        service = RunService(SimpleNamespace(require_owner=AsyncMock()), SimpleNamespace(), repository=repo)
        with patch.object(service, 'recovery_snapshot', AsyncMock(return_value=True)):
            cid, config = await service.prepare_recovery('run', 7, None, 'admission')
        self.assertEqual(cid, 11)
        self.assertEqual(config['configurable']['admission_ticket'], 'new')
        self.assertEqual(config['callbacks'][0].charged, 1234)
        repo.bind_admission.assert_awaited_once_with('run', 'new', 'admission')

    async def test_foreign_user_never_reads_checkpoint_or_claims_run(self):
        repo = SimpleNamespace(get=AsyncMock(return_value=self.fixture_run()), claim_recovery=AsyncMock())
        service = RunService(SimpleNamespace(), SimpleNamespace(), repository=repo)
        graph = SimpleNamespace(aget_state=AsyncMock())
        with self.assertRaises(HTTPException) as error: await service.prepare_recovery('run', 8, graph, 'ticket')
        self.assertEqual(error.exception.status_code, 404)
        repo.claim_recovery.assert_not_awaited(); graph.aget_state.assert_not_awaited()

    async def test_repository_rejects_active_newer_or_already_recovered_run(self):
        @asynccontextmanager
        async def transaction(): yield
        for update, active, latest in [({}, 'active', 'run'), ({}, None, 'newer'), ({'recovery_count': 1}, None, 'run'), ({'status': 'cancelled'}, None, 'run')]:
            db = SimpleNamespace(transaction=transaction, fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping=self.fixture_run(**update))),
                                 fetch_val=AsyncMock(return_value=active), execute=AsyncMock())
            repo = RunRepository(db)
            with patch.object(repo, '_lock_conversation', AsyncMock()), patch.object(repo, 'latest', AsyncMock(return_value={'run_id': latest})):
                with self.assertRaises(HTTPException): await repo.claim_recovery(11, 7, 'run')
            db.execute.assert_not_awaited()

    def test_callback_manager_metrics_keep_pending_call_reservations(self):
        metrics = RunMetrics()
        metrics.reserve('pending', 10, {'invocation_params': {'max_tokens': 1000}})
        snapshot = metrics_from({'callbacks': SimpleNamespace(handlers=[metrics])})
        self.assertGreaterEqual(snapshot['budget_charged_tokens'], 1000)
        self.assertEqual(RunMetrics(snapshot).charged, snapshot['budget_charged_tokens'])

    async def test_model_start_persists_reservation_before_provider_can_run(self):
        persist = AsyncMock()
        metrics = RunMetrics(persist=persist)
        await metrics.on_llm_start({}, ['prompt'], run_id='call', invocation_params={'max_tokens': 1000})
        snapshot = persist.call_args.args[0]
        self.assertGreaterEqual(snapshot['budget_charged_tokens'], 1000)
        self.assertEqual(snapshot['llm_calls'], 1)
        self.assertFalse(snapshot['token_usage_complete'])
        persist.side_effect = RuntimeError('SQL unavailable')
        with self.assertRaises(RuntimeError):
            await metrics.on_llm_start({}, ['next'], run_id='next', invocation_params={'max_tokens': 1000})

    async def test_http_recovery_binds_principal_and_releases_ticket_on_rejection(self):
        rid = 'ae0bd008-98cf-4018-b809-e80860386b01'
        admission = SimpleNamespace(acquire=AsyncMock(return_value='ticket'), release=AsyncMock())
        service = SimpleNamespace(prepare_recovery=AsyncMock(side_effect=HTTPException(409, 'stale')))
        main.app.dependency_overrides[main.require_principal] = lambda: Principal(user_id=7)
        try:
            with patch.object(main, 'execution_admission', admission), patch.object(main, 'run_service', service), \
                 patch.object(main, 'get_graph', AsyncMock(return_value='graph')):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                    response = await client.post(f'/runs/{rid}/recover', json={'user_id': 8})
                    self.assertEqual(response.status_code, 409)
                    service.prepare_recovery.assert_awaited_once_with(rid, 7, 'graph', 'ticket')
                    admission.release.assert_awaited_once_with('ticket')
                    response = await client.post('/runs/invalid/recover')
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(admission.acquire.await_count, 1)
        finally: main.app.dependency_overrides.clear()

    async def test_http_recovery_without_service_identity_cannot_get_admission(self):
        admission = SimpleNamespace(acquire=AsyncMock())
        with patch.object(main, 'execution_admission', admission):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                response = await client.post('/runs/ae0bd008-98cf-4018-b809-e80860386b01/recover')
                self.assertIn(response.status_code, (401, 403))
        admission.acquire.assert_not_awaited()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_migration_replays_without_altering_existing_column(self):
        @asynccontextmanager
        async def connection(): yield database
        database = SimpleNamespace(connection=connection, fetch_val=AsyncMock(side_effect=[1, None, 1, 6, 1]), execute=AsyncMock())
        await migrate.apply_task_recovery_migration(database)
        sql = [call.args[0] for call in database.execute.call_args_list]
        self.assertTrue(any('CREATE TABLE' in text for text in sql))
        self.assertFalse(any('ALTER TABLE' in text for text in sql))
        self.assertTrue(any('INSERT IGNORE' in text for text in sql))

    async def test_changed_migration_checksum_fails_and_releases_schema_lock(self):
        @asynccontextmanager
        async def connection(): yield database
        database = SimpleNamespace(connection=connection, fetch_val=AsyncMock(side_effect=[1, 'wrong', 1]), execute=AsyncMock())
        with self.assertRaises(RuntimeError): await migrate.apply_task_recovery_migration(database)
        database.execute.assert_not_awaited()
        self.assertIn('RELEASE_LOCK', database.fetch_val.call_args.args[0])
