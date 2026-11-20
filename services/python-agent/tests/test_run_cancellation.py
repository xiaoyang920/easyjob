"""Explicit stops interrupt awaited work without cancelling unrelated runs or subscribers."""
import asyncio
from uuid import uuid4
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse
import httpx
import socket
import uvicorn
from contextlib import AsyncExitStack, asynccontextmanager
from app import main
from app.security.principal import Principal
from app.services.executor_heartbeat import maintain_executor, cancel_local_run, _executors
from app.services.stream_delivery import StreamDelivery
from test_runtime_operations import FrameDatabase


class RunCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_stop_does_not_interrupt_the_first_stops_cleanup(self):
        ready, cleaning, release = [asyncio.Event() for _ in range(3)]
        async def owner():
            async with maintain_executor(SimpleNamespace(), {'configurable': {'run_id': 'repeat', 'execution_token': 't'}}):
                ready.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
        task = asyncio.create_task(owner())
        await ready.wait()
        cancel_local_run('repeat')
        await cleaning.wait()
        cancel_local_run('repeat')
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(_executors)

    async def test_real_public_http_can_stop_one_slow_stream_and_serve_overview_while_another_runs(self):
        ids = {cid: str(uuid4()) for cid in (11, 12)}
        states = {rid: {'execution_token': rid, 'status': 'running', 'deadline': datetime.utcnow() + timedelta(minutes=1)} for rid in ids.values()}
        ready = {cid: asyncio.Event() for cid in ids}
        interrupted = asyncio.Event()
        finish_other = asyncio.Event()
        database = FrameDatabase()
        repo = SimpleNamespace(get=AsyncMock(side_effect=lambda rid: dict(states[rid])), fail=AsyncMock())
        delivery = StreamDelivery(database, SimpleNamespace(release=AsyncMock()), repo)

        async def chat(request, principal):
            cid, rid = request.conversation_id, ids[request.conversation_id]
            async def source():
                yield 'data:started\n\n'
                ready[cid].set()
                try:
                    if cid == 11:
                        await asyncio.Event().wait()
                    else:
                        await finish_other.wait()
                except asyncio.CancelledError:
                    if cid == 11:
                        interrupted.set()
                    raise
                yield 'data:[DONE]\n\n'
            delivery.start(rid, rid, source(), rid)
            return StreamingResponse(delivery.follow(rid, rid), media_type='text/event-stream')

        async def cancel(cid, uid):
            states[ids[cid]]['status'] = 'cancelled'
            return {'status': 'cancelled', 'runId': ids[cid]}

        app = SimpleNamespace(ChatRequest=main.ChatRequest, chat_stream=chat, cancel_chat=main.cancel_chat,
                              run_overview=AsyncMock(return_value={'available': True}))
        from app import public_api
        from app.security import gateway
        http_app = FastAPI()
        public_api.install(http_app, app)

        @asynccontextmanager
        async def subscribed(identity):
            yield asyncio.Event()

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(http_app, log_level='error', lifespan='off'))
        running = asyncio.create_task(server.serve(sockets=[listener]))
        claims = {'sub': '7', 'sid': 'a' * 64, 'ver': 1}
        with patch.object(gateway, 'verify', return_value=claims), \
             patch.object(public_api.sessions, 'subscribe', side_effect=subscribed), \
             patch.object(main, 'run_repository', SimpleNamespace(cancel=AsyncMock(side_effect=cancel))), \
             patch.object(main, 'conversation_service', SimpleNamespace(require_owner=AsyncMock())):
            try:
                async with asyncio.timeout(3):
                    while not server.started:
                        if running.done():
                            await running
                        await asyncio.sleep(.01)
                async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=3,
                        headers={'X-Easyjob-Identity': 'offline-verified'}, trust_env=False) as client, AsyncExitStack() as stack:
                    responses = [await stack.enter_async_context(client.stream('POST', '/api/agent/chat/stream', json={
                        'conversationId': cid, 'message': 'offline slow provider', 'requestId': str(uuid4())})) for cid in (11, 12)]
                    lines = [response.aiter_lines() for response in responses]
                    for response, iterator in zip(responses, lines):
                        self.assertEqual(response.status_code, 200)
                        async with asyncio.timeout(3):
                            while not (line := await anext(iterator)).startswith('data:'):
                                pass
                        self.assertEqual(line, 'data:started')
                    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), 1)
                    reply = await client.post('/api/agent/chat/11/cancel')
                    self.assertEqual(reply.json()['data']['status'], 'cancelled')
                    await asyncio.wait_for(interrupted.wait(), 1)
                    overview = await client.get('/api/agent/run-overview')
                    self.assertEqual(overview.json()['data'], {'available': True})
                    self.assertEqual(states[ids[12]]['status'], 'running')
                    frames = [line async for line in lines[0]]
                    self.assertTrue(any('[DONE]' in frame for frame in frames))
                    self.assertTrue(any('"status":"cancelled"' in frame for frame in frames))
                    finish_other.set()
                    self.assertTrue(any('[DONE]' in frame for frame in [line async for line in lines[1]]))
            finally:
                finish_other.set()
                await delivery.shutdown()
                server.should_exit = True
                try:
                    await asyncio.wait_for(running, 3)
                finally:
                    listener.close()
        self.assertFalse(_executors)

    async def test_stop_interrupts_waiting_model_and_releases_capacity_without_waiting_for_heartbeat(self):
        database = FrameDatabase()
        admission = SimpleNamespace(release=AsyncMock())
        state = {'run_id': 'stop-run', 'status': 'running', 'execution_token': 'token',
                 'deadline': datetime.utcnow() + timedelta(minutes=1)}
        repo = SimpleNamespace(get=AsyncMock(side_effect=lambda rid: dict(state)), fail=AsyncMock())
        delivery = StreamDelivery(database, admission, repo)
        waiting, interrupted, other_waiting, finish_other = [asyncio.Event() for _ in range(4)]

        async def source():
            yield 'data:started\n\n'
            waiting.set()
            try:
                await asyncio.Event().wait()  # A provider that will never finish on its own.
            except asyncio.CancelledError:
                interrupted.set()
                raise
            yield 'data:must-not-be-published\n\n'

        async def other_run():
            async with maintain_executor(repo, {'configurable': {'run_id': 'other', 'execution_token': 'other-token'}}):
                other_waiting.set()
                await finish_other.wait()

        async def commit_cancel(cid, uid):
            state['status'] = 'cancelled'
            return {'status': 'cancelled', 'runId': state['run_id']}

        control_repo = SimpleNamespace(cancel=AsyncMock(side_effect=commit_cancel))
        with patch.object(main, 'run_repository', control_repo), \
             patch.object(main, 'conversation_service', SimpleNamespace(require_owner=AsyncMock())):
            delivery.start('stop-run', 'token', source(), 'ticket')
            other = asyncio.create_task(other_run())
            try:
                await asyncio.wait_for(asyncio.gather(waiting.wait(), other_waiting.wait()), 1)
                producer = delivery.tasks[('stop-run', 'token')]
                result = await asyncio.wait_for(main.cancel_chat(11, 7, Principal(user_id=7)), .5)
                self.assertEqual(result['status'], 'cancelled')
                await asyncio.wait_for(interrupted.wait(), .5)
                await asyncio.wait_for(asyncio.gather(producer, return_exceptions=True), 1)
                self.assertFalse(other.done())
                admission.release.assert_awaited_once_with('ticket')
                self.assertFalse(delivery.tasks)
                replay = ''.join([frame async for frame in delivery.follow('stop-run', 'token')])
                self.assertIn('"status":"cancelled"', replay)
                self.assertIn('[DONE]', replay)
                self.assertNotIn('[ERROR]', replay)
                self.assertNotIn('must-not-be-published', replay)
                repo.fail.assert_not_awaited()
            finally:
                finish_other.set()
                await other
                await delivery.shutdown()
        self.assertFalse(_executors)

    async def test_failed_or_denied_cancel_and_in_progress_save_never_interrupt_execution(self):
        for outcome in (HTTPException(403, 'owner'), HTTPException(500, 'rollback'), {'status': 'saving'}, {'status': 'draft_saved'}):
            entered, release = asyncio.Event(), asyncio.Event()
            async def owner():
                async with maintain_executor(SimpleNamespace(), {'configurable': {'run_id': 'run', 'execution_token': 't'}}):
                    entered.set()
                    await release.wait()
            task = asyncio.create_task(owner())
            await entered.wait()
            repo = SimpleNamespace(cancel=AsyncMock(side_effect=outcome if isinstance(outcome, Exception) else None,
                                                   return_value=outcome if isinstance(outcome, dict) else None))
            with patch.object(main, 'run_repository', repo), \
                 patch.object(main, 'conversation_service', SimpleNamespace(require_owner=AsyncMock())):
                try:
                    if isinstance(outcome, Exception):
                        with self.assertRaises(HTTPException):
                            await main.cancel_chat(11, 7, Principal(user_id=7))
                    else:
                        await main.cancel_chat(11, 7, Principal(user_id=7))
                    self.assertFalse(task.done())
                    self.assertFalse(task.cancelling())
                finally:
                    release.set()
                    await task
        self.assertFalse(_executors)

    async def test_nested_execution_registration_remains_cancellable_after_inner_scope_exits(self):
        ready = asyncio.Event()
        config = {'configurable': {'run_id': 'nested', 'execution_token': 't'}}
        async def owner():
            async with maintain_executor(SimpleNamespace(), config):
                async with maintain_executor(SimpleNamespace(), config):
                    pass
                ready.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(owner())
        await ready.wait()
        cancel_local_run('nested')
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(_executors)
