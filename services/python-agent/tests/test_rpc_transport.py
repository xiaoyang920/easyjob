"""Internal RPC stays unary; browser workflows are tested through public_api."""
import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
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

    def test_only_internal_unary_rpc_remains_in_both_directions(self):
        agent = pb.DESCRIPTOR.services_by_name['AgentRpc']
        self.assertEqual([method.name for method in agent.methods], ['ServiceQuery'])
        for service in pb.DESCRIPTOR.services_by_name.values():
            self.assertTrue(all(not method.client_streaming and not method.server_streaming for method in service.methods))
        self.assertFalse(hasattr(pb, 'ChatRequest'))
        self.assertFalse(hasattr(pb, 'Frame'))


class RpcServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for target in (patch.object(settings, 'AGENT_SERVICE_KEY', KEY),
                       patch('app.security.delegation.verify', return_value={})):
            target.start()
            self.addCleanup(target.stop)
        self.identity = pb.Identity(user_id=7, service_key=KEY)

    async def test_internal_query_preserves_authenticated_owner_and_int64_values(self):
        request = pb.AgentQuery(identity=self.identity, kind='profile_topics', name=str(BIG_ID))
        request.edit.CopyFrom(codec.encode({'id': BIG_ID}).object)
        query = AsyncMock(return_value={'id': BIG_ID, 'items': []})
        with patch('app.services.service_queries.query', query):
            reply = await server.AgentRpc().ServiceQuery(request, None)
        self.assertEqual(codec.decode(reply.data), {'id': BIG_ID, 'items': []})
        query.assert_awaited_once_with(request, 7)
        self.assertEqual(codec.decode_object(query.call_args.args[0].edit)['id'], BIG_ID)

    async def test_authentication_rejects_before_application(self):
        query = AsyncMock()
        with patch('app.services.service_queries.query', query):
            reply = await server.AgentRpc().ServiceQuery(pb.AgentQuery(
                identity=pb.Identity(user_id=7, service_key='wrong'), kind='health'), None)
        self.assertEqual(reply.error.status, 401)
        query.assert_not_awaited()

    async def test_business_conflict_preserved_and_internal_exception_redacted(self):
        query = AsyncMock(side_effect=HTTPException(409, '操作版本已改变'))
        request = pb.AgentQuery(identity=self.identity, kind='feedback_review')
        with patch('app.services.service_queries.query', query):
            self.assertEqual((await server.AgentRpc().ServiceQuery(request, None)).error.status, 409)
            query.side_effect = RuntimeError('secret diagnostic')
            reply = await server.AgentRpc().ServiceQuery(request, None)
        self.assertEqual(reply.error.status, 500)
        self.assertNotIn('secret', reply.error.message)

    async def test_observation_credential_cannot_mutate_or_read_private_records(self):
        query = AsyncMock(return_value={'status': 'ok'})
        with patch('app.security.delegation.verify', return_value='service_observe'), \
                patch('app.services.service_queries.query', query):
            for kind in ('feedback_review', 'runs', 'profile_topics'):
                reply = await server.AgentRpc().ServiceQuery(pb.AgentQuery(identity=self.identity, kind=kind), None)
                self.assertEqual(reply.error.status, 403)
            query.assert_not_awaited()
            reply = await server.AgentRpc().ServiceQuery(pb.AgentQuery(identity=self.identity, kind='health'), None)
            self.assertTrue(reply.HasField('data'))

    async def test_blog_client_conflict_and_optional_optimistic_lock(self):
        remote = SimpleNamespace(SaveDraft=AsyncMock(return_value=pb.Reply(error=pb.Error(status=409, message='conflict'))))
        payload = dict(runId='run', executionToken='token', articleId=str(BIG_ID), title='标题', summary='',
                       markdown='正文', html='<p>正文</p>', draftHash='a'*64, baseDraftHash='b'*64,
                       expectedRevisionId='5', expectedLockVersion=0)
        with patch.object(blog_client, 'client', return_value=remote), \
                patch('app.rpc.discovery.catalog.enabled', False):
            with self.assertRaises(blog_client.ServiceError) as error:
                await blog_client.save_draft(7, payload)
        self.assertEqual(error.exception.status, 409)
        request = remote.SaveDraft.call_args.args[0]
        self.assertEqual(request.article_id, BIG_ID)
        self.assertTrue(request.HasField('expected_lock_version'))
        self.assertEqual(request.expected_lock_version, 0)
        self.assertEqual(request.base_draft_hash, 'b'*64)
        self.assertEqual(remote.SaveDraft.await_count, 1)
