"""Transport tests are offline; actual Java/Python interoperability has a separate CI job."""
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from starlette.responses import StreamingResponse
from app.config import settings
from app.rpc import codec, server, blog_client
from app.rpc.generated import easyjob_rpc_pb2 as pb

KEY = 'rpc-offline-service-key-32-bytes!!'
BIG_ID = 9007199254740993


class RpcCodecTests(unittest.TestCase):
    def test_binary_round_trip_preserves_ids_null_bool_and_empty_containers(self):
        value = {'id': BIG_ID, 'text': '中文\n正文', 'none': None, 'true': True,
                 'false': False, 'float': 0.25, 'array': [], 'object': {}, 'nested': [1, {'id': str(BIG_ID)}]}
        self.assertEqual(codec.decode(pb.Value.FromString(codec.encode(value).SerializeToString())), value)

    def test_unbounded_or_nonfinite_values_rejected(self):
        for value in (float('nan'), float('inf'), 1 << 64):
            with self.assertRaises(ValueError): codec.encode(value)
        value = []
        for _ in range(35): value = [value]
        with self.assertRaises(ValueError): codec.encode(value)

    def test_service_identity_is_fail_closed(self):
        with patch.object(settings, 'AGENT_SERVICE_KEY', KEY):
            self.assertEqual(server.principal(pb.Identity(user_id=BIG_ID, service_key=KEY)).user_id, BIG_ID)
            for identity in (pb.Identity(user_id=7, service_key='wrong'), pb.Identity(user_id=0, service_key=KEY)):
                with self.assertRaises(HTTPException): server.principal(identity)


class RpcServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        key = patch.object(settings, 'AGENT_SERVICE_KEY', KEY)
        key.start(); self.addCleanup(key.stop)
        self.identity = pb.Identity(user_id=7, service_key=KEY)

    async def test_owner_and_large_pagination_cursors_reach_application_unchanged(self):
        fn = AsyncMock(return_value={'data': {'messages': [], 'cursor': str(BIG_ID)}})
        app = SimpleNamespace(get_messages=fn)
        request = pb.HistoryRequest(identity=self.identity, conversation_id=42, limit=30, before=BIG_ID)
        reply = await server.AgentRpc(app).Messages(request, None)
        self.assertEqual(codec.decode(reply.data)['data']['cursor'], str(BIG_ID))
        args = fn.call_args.args
        self.assertEqual(args[:2], (42, 7)); self.assertEqual(args[4], BIG_ID)
        self.assertEqual(args[2].user_id, 7)

    async def test_validation_and_auth_fail_before_application(self):
        fn = AsyncMock()
        service = server.AgentRpc(SimpleNamespace(get_messages=fn))
        reply = await service.Messages(pb.HistoryRequest(identity=self.identity, conversation_id=42, limit=100), None)
        self.assertEqual(reply.error.status, 422)
        reply = await service.Messages(pb.HistoryRequest(identity=pb.Identity(user_id=7, service_key='wrong'), conversation_id=42), None)
        self.assertEqual(reply.error.status, 401)
        fn.assert_not_awaited()

    async def test_business_conflict_preserved_and_internal_exception_redacted(self):
        fn = AsyncMock(side_effect=HTTPException(409, '运行状态已改变'))
        service = server.AgentRpc(SimpleNamespace(cancel_chat=fn))
        request = pb.ConversationRequest(identity=self.identity, conversation_id=42)
        self.assertEqual((await service.Cancel(request, None)).error.status, 409)
        fn.side_effect = RuntimeError('secret diagnostic')
        reply = await service.Cancel(request, None)
        self.assertEqual(reply.error.status, 500)
        self.assertNotIn('secret', reply.error.message)

    async def test_stream_preserves_markers_and_closes_subscriber_without_cancelling_run(self):
        closed = []
        async def frames():
            try:
                yield 'data:__RUN__:{"id":"42"}\n\n'
                yield ': keepalive\n\n'
                yield 'data:正文\\n第二行\n\n'
            finally: closed.append(True)
        cancel = AsyncMock()
        service = server.AgentRpc(SimpleNamespace(replay_events=AsyncMock(return_value=StreamingResponse(frames())), cancel_chat=cancel))
        stream = service.RunEvents(pb.RunRequest(identity=self.identity, run_id='12345678-1234-1234-1234-123456789abc'), None)
        self.assertEqual((await anext(stream)).data, '__RUN__:{"id":"42"}')
        self.assertTrue((await anext(stream)).heartbeat)
        await stream.aclose()
        self.assertEqual(closed, [True]); cancel.assert_not_awaited()

    async def test_questions_snapshot_and_filters_remain_typed(self):
        fn = AsyncMock(return_value={'data': {'items': []}})
        service = server.AgentRpc(SimpleNamespace(question_index=fn))
        await service.Questions(pb.HistoryRequest(identity=self.identity, conversation_id=42, limit=200, after=1, snapshot=BIG_ID), None)
        self.assertEqual(fn.call_args.args[3:], (1, 200, BIG_ID))

    async def test_blog_client_conflict_and_optional_optimistic_lock(self):
        remote = SimpleNamespace(SaveDraft=AsyncMock(return_value=pb.Reply(error=pb.Error(status=409, message='conflict'))))
        payload = dict(runId='run', executionToken='token', articleId=str(BIG_ID), title='标题', summary='',
                       markdown='正文', html='<p>正文</p>', draftHash='a'*64, baseDraftHash='b'*64,
                       expectedRevisionId='5', expectedLockVersion=0)
        with patch.object(blog_client, 'client', return_value=remote):
            with self.assertRaises(blog_client.ServiceError) as error:
                await blog_client.save_draft(7, payload)
        self.assertEqual(error.exception.status, 409)
        request = remote.SaveDraft.call_args.args[0]
        self.assertEqual(request.article_id, BIG_ID)
        self.assertTrue(request.HasField('expected_lock_version'))
        self.assertEqual(request.expected_lock_version, 0)
        self.assertEqual(request.base_draft_hash, 'b'*64)
        self.assertEqual(remote.SaveDraft.await_count, 1)


if __name__ == '__main__': unittest.main()
