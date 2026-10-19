"""Explicit stops interrupt awaited work without cancelling unrelated runs or subscribers."""
import asyncio
from uuid import uuid4
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.responses import StreamingResponse
import grpc
from app import main
from app.security.principal import Principal
from app.services.executor_heartbeat import maintain_executor, cancel_local_run, _executors
from app.services.stream_delivery import StreamDelivery
from test_runtime_operations import FrameDatabase
from app.rpc.server import AgentRpc
from app.rpc.generated import easyjob_rpc_pb2 as pb, easyjob_rpc_pb2_grpc as api
from app.rpc.codec import decode
from app.config import settings


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

    async def test_real_rpc_channel_can_stop_one_slow_stream_and_serve_overview_while_another_runs(self):
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
        key = 'offline-cancellation-test-key-32-bytes'
        server = grpc.aio.server()
        api.add_AgentRpcServicer_to_server(AgentRpc(app), server)
        port = server.add_insecure_port('127.0.0.1:0')
        self.assertGreater(port, 0)
        await server.start()
        with patch.object(settings, 'AGENT_SERVICE_KEY', key), \
             patch.object(main, 'run_repository', SimpleNamespace(cancel=AsyncMock(side_effect=cancel))), \
             patch.object(main, 'conversation_service', SimpleNamespace(require_owner=AsyncMock())):
            try:
                async with grpc.aio.insecure_channel(f'127.0.0.1:{port}') as channel:
                    stub = api.AgentRpcStub(channel)
                    identity = pb.Identity(user_id=7, service_key=key)
                    streams = [stub.ChatStream(pb.ChatRequest(identity=identity, conversation_id=cid, message='offline slow provider', request_id=str(uuid4()))) for cid in (11, 12)]
                    try:
                        for stream in streams:
                            self.assertEqual((await anext(stream.__aiter__())).data, 'started')
                        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), 1)
                        reply = await stub.Cancel(pb.ConversationRequest(identity=identity, conversation_id=11), timeout=1)
                        self.assertEqual(decode(reply.data)['status'], 'cancelled')
                        await asyncio.wait_for(interrupted.wait(), 1)
                        overview = await stub.RunOverview(pb.UserRequest(identity=identity), timeout=1)
                        self.assertEqual(decode(overview.data), {'available': True})
                        self.assertEqual(states[ids[12]]['status'], 'running')
                        frames = [frame.data async for frame in streams[0] if frame.HasField('data')]
                        self.assertIn('[DONE]', frames)
                        self.assertTrue(any('"status":"cancelled"' in frame for frame in frames))
                        finish_other.set()
                        other_frames = [frame.data async for frame in streams[1] if frame.HasField('data')]
                        self.assertIn('[DONE]', other_frames)
                    finally:
                        for stream in streams:
                            stream.cancel()
            finally:
                finish_other.set()
                await delivery.shutdown()
                await server.stop(0)
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
