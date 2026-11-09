"""Bare continuation commands share checkpoint recovery with the explicit button."""
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from app import main
from app.services.run_service import RunService
from app.services.run_repository import RunRepository
from app.services.checkpoint_store import LatestRunRedisSaver
from app.services.executor_heartbeat import maintain_executor
from app.security.principal import Principal


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.run = dict(run_id='r', user_id=7, conversation_id=11, status='cancelled',
            draft_article_id=None, execution_token='old', result_json='{"user_message_id":"u"}')
        self.repo = SimpleNamespace(latest=AsyncMock(side_effect=lambda *args: dict(self.run)),
            get=AsyncMock(side_effect=lambda *args: dict(self.run)), expire_existing=AsyncMock(),
            create=AsyncMock(), has_memory_write=AsyncMock(return_value=False),
            bind_admission=AsyncMock(), fail=AsyncMock())
        self.conv = SimpleNamespace(require_owner=AsyncMock(), resolve_origin=AsyncMock(return_value=None), add_message=AsyncMock())
        self.history = SimpleNamespace(previous=AsyncMock())
        self.service = RunService(self.conv, SimpleNamespace(), repository=self.repo, history=self.history)
        self.snapshot = SimpleNamespace(next=('main_agent',), tasks=[], values={
            'run_id': 'r', 'user_id': 7, 'conversation_id': 11, 'task_results': {'search': {'status': 'succeeded', 'result': 'retained'}}})
        self.graph = SimpleNamespace(aget_state=AsyncMock(return_value=self.snapshot))

    def request(self, text='继续', **extra):
        return main.ChatRequest(user_id=7, conversation_id=11, message=text, **extra)

    async def test_exact_command_uses_latest_owned_run_without_importing_history_results(self):
        for text in ['继续', ' 重试！ ', '继续上次任务。', '继续上次未完成任务']:
            self.assertEqual((await self.service.continuation_target(self.request(text)))['run_id'], 'r')
        self.repo.create.assert_not_awaited(); self.conv.add_message.assert_not_awaited()
        self.history.previous.assert_not_awaited()
        self.conv.resolve_origin.assert_awaited_with(11, 7, None)

    async def test_requirements_attachments_and_editor_inputs_remain_new_requests(self):
        cases = [self.request('继续，但改成英文'), self.request('继续写第二章'),
            self.request('继续', image_paths=['ai-chat/7/a.png']), self.request('继续\n\n<easyjob-writing-context>quote</easyjob-writing-context>'),
            main.ChatRequest(user_id=7, message='继续')]
        for request in cases:
            self.assertIsNone(await self.service.continuation_target(request))
        self.repo.latest.assert_not_awaited()

    async def test_finished_and_empty_conversation_are_normal_followups_but_approval_is_not_replayed(self):
        self.repo.latest.return_value = None; self.repo.latest.side_effect = None
        self.assertIsNone(await self.service.continuation_target(self.request()))
        self.repo.latest.side_effect = lambda *args: dict(self.run)
        self.run['status'] = 'succeeded'
        self.assertIsNone(await self.service.continuation_target(self.request()))
        self.run['status'] = 'awaiting_approval'
        with self.assertRaises(HTTPException) as error: await self.service.continuation_target(self.request())
        self.assertEqual(error.exception.status_code, 409)

    async def test_wrong_owner_or_article_binding_cannot_select_a_checkpoint(self):
        self.conv.require_owner.side_effect = HTTPException(404, 'owner')
        with self.assertRaises(HTTPException): await self.service.continuation_target(self.request())
        self.repo.latest.assert_not_awaited()
        self.conv.require_owner.side_effect = None
        self.conv.resolve_origin.side_effect = HTTPException(409, 'source')
        with self.assertRaises(HTTPException): await self.service.continuation_target(self.request(origin_article_id=42))
        self.repo.latest.assert_not_awaited(); self.graph.aget_state.assert_not_awaited()

    async def test_chat_command_claims_original_run_and_passes_none_to_the_graph(self):
        claimed = {**self.run, 'status': 'running', 'execution_token': 'new'}
        self.repo.claim_recovery = AsyncMock(return_value=claimed)
        admission = SimpleNamespace(acquire=AsyncMock(return_value='ticket'), release=AsyncMock())
        with patch.object(main, 'run_service', self.service), patch.object(main, 'execution_admission', admission):
            cid, config, graph_input = await main._prepare_chat(self.request(), self.graph)
        self.assertEqual(cid, 11); self.assertIsNone(graph_input)
        self.assertEqual(config['configurable']['thread_id'], 'run_r')
        self.assertEqual(config['configurable']['execution_token'], 'new')
        self.assertEqual(config['configurable']['recovery_input_id'], 'u')
        self.repo.claim_recovery.assert_awaited_once_with(11, 7, 'r')
        self.repo.bind_admission.assert_awaited_once_with('r', 'new', 'ticket')
        self.repo.create.assert_not_awaited(); self.conv.add_message.assert_not_awaited()
        self.history.previous.assert_not_awaited()

    async def test_invalid_or_cancelled_business_checkpoint_is_rejected_without_silent_new_run(self):
        for state in [dict(self.snapshot.values, cancelled=True), dict(self.snapshot.values, draft_document={'body': 'x'})]:
            self.snapshot.values = state
            admission = SimpleNamespace(acquire=AsyncMock(return_value='ticket'), release=AsyncMock())
            with patch.object(main, 'run_service', self.service), patch.object(main, 'execution_admission', admission):
                with self.assertRaises(HTTPException) as error: await main._prepare_chat(self.request(), self.graph)
            self.assertEqual(error.exception.status_code, 409)
            admission.release.assert_awaited_once_with('ticket')
        self.repo.create.assert_not_awaited(); self.conv.add_message.assert_not_awaited()

    async def test_active_command_reconnects_before_admission_and_never_invokes_graph(self):
        self.run['status'] = 'running'
        admission = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock())
        async def frames(*args):
            yield 'data:__RUN_ID__:r\n\n'; yield 'data:[DONE]\n\n'
        with patch.object(main, 'run_service', self.service), patch.object(main, 'execution_admission', admission), \
                patch.object(main.stream_delivery, 'start') as start, patch.object(main.stream_delivery, 'follow', frames):
            cid, config, state = await main._prepare_chat(self.request(), self.graph)
            response = main._stream(self.graph, state, cid, 7, config)
            output = ''.join([frame async for frame in response.body_iterator])
        self.assertIn('__RECOVERED_RUN__:', output); self.assertIn('"inputMessageId": "u"', output)
        admission.acquire.assert_not_awaited(); start.assert_not_called(); self.graph.aget_state.assert_not_awaited()

    async def test_stop_only_interrupts_the_cancelled_generation_and_never_exposes_token(self):
        ready = [asyncio.Event(), asyncio.Event()]; release = asyncio.Event()
        async def owner(token, entered):
            async with maintain_executor(SimpleNamespace(), {'configurable': {'run_id': 'r', 'execution_token': token}}):
                entered.set(); await release.wait()
        old = asyncio.create_task(owner('old', ready[0])); new = asyncio.create_task(owner('new', ready[1]))
        await asyncio.gather(*(event.wait() for event in ready))
        self.repo.cancel = AsyncMock(return_value={'status': 'cancelled', 'runId': 'r', '_execution_token': 'old'})
        try:
            with patch.object(main, 'run_repository', self.repo), patch.object(main, 'conversation_service', self.conv):
                result = await main.cancel_chat(11, 7, Principal(user_id=7))
            await asyncio.gather(old, return_exceptions=True)
            self.assertTrue(old.cancelled()); self.assertFalse(new.cancelling())
            self.assertEqual(result, {'status': 'cancelled', 'runId': 'r'})
        finally:
            release.set(); await asyncio.gather(old, new, return_exceptions=True)

    async def test_repeated_explicit_continuation_keeps_metrics_and_uses_a_fresh_generation(self):
        self.run.update(recovery_count=3, result_json=json.dumps({'metrics': {'budget_charged_tokens': 123, 'llm_calls': 2}}))
        @asynccontextmanager
        async def transaction(): yield
        database = SimpleNamespace(transaction=transaction, fetch_one=AsyncMock(side_effect=lambda *args: SimpleNamespace(_mapping=dict(self.run))),
            fetch_val=AsyncMock(return_value=None), execute=AsyncMock())
        repo = RunRepository(database)
        with patch.object(repo, '_lock_conversation', AsyncMock()), patch.object(repo, 'latest', AsyncMock(return_value=self.run)), \
                patch.object(repo, 'get', AsyncMock(return_value=self.run)):
            await repo.claim_recovery(11, 7, 'r')
        args = database.execute.await_args.args
        self.assertIn('recovery_count=recovery_count+1', args[0])
        self.assertNotEqual(args[1]['token'], 'old')
        self.assertEqual(self.service.config(self.run)['callbacks'][0].charged, 123)

    async def test_real_cancelled_graph_resumes_main_without_repeating_completed_retrieval(self):
        ready = asyncio.Event(); calls = []; attempts = 0
        self.run['status'] = 'running'
        @asynccontextmanager
        async def writer(rid, token):
            if self.run['execution_token'] != token or self.run['status'] != 'running':
                raise HTTPException(409, 'old generation')
            yield
        saver = LatestRunRedisSaver.__new__(LatestRunRedisSaver); BaseCheckpointSaver.__init__(saver)
        backend = InMemorySaver(); saver.legacy = backend; saver._backend = AsyncMock(return_value=backend)
        async def retrieve(state):
            calls.append('retrieve'); return {**state, 'evidence': 'retained'}
        async def decide(state):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                ready.set(); await asyncio.Event().wait()
            calls.append(state['evidence']); return {**state, 'final_reply': 'done'}
        builder = StateGraph(dict)
        builder.add_node('execute_tool', retrieve); builder.add_node('main_agent', decide)
        builder.add_edge(START, 'execute_tool'); builder.add_edge('execute_tool', 'main_agent'); builder.add_edge('main_agent', END)
        graph = builder.compile(checkpointer=saver)
        async def claim(*args):
            self.run.update(status='running', execution_token='new'); return dict(self.run)
        self.repo.claim_recovery = AsyncMock(side_effect=claim)
        with patch('app.services.run_repository.run_repository', SimpleNamespace(checkpoint_writer=writer)):
            task = asyncio.create_task(graph.ainvoke({'run_id': 'r', 'user_id': 7, 'conversation_id': 11}, self.service.config(self.run)))
            await asyncio.wait_for(ready.wait(), 2)
            self.run['status'] = 'cancelled'; task.cancel('user_stop')
            await asyncio.gather(task, return_exceptions=True)
            snapshot = await graph.aget_state(self.service.config(self.run))
            self.assertEqual(snapshot.next, ('main_agent',))
            _, config = await self.service.prepare_recovery('r', 7, graph, 'ticket')
            result = await graph.ainvoke(None, config)
        self.assertEqual(result['final_reply'], 'done')
        self.assertEqual(calls, ['retrieve', 'retained']); self.assertEqual(attempts, 2)
