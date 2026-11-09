"""Browser contract and gateway trust boundary; no network, models or database."""
import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app import public_api
from app.security import gateway, delegation
from app.security.stream_sessions import StreamSessions, guarded_frames

BIG = 9007199254740993
RUN = 'b914ff83-cc73-4a1a-90f1-5908c8265326'


class PublicApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.application = SimpleNamespace(ChatRequest=SimpleNamespace, ResumeRequest=SimpleNamespace)
        self.app = FastAPI()
        public_api.install(self.app, self.application)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        key = patch.object(gateway, 'public_key', return_value=self.key.public_key())
        key.start(); self.addCleanup(key.stop)

    def token(self, target_path, target_method='GET', **changes):
        now = int(time.time())
        claims = dict(iss='easyjob-gateway', aud='easyjob-agent', sub='7', sid='a'*64,
                      ver=2, kind='user', token_use='gateway', iat=now, nbf=now-1,
                      exp=now+15, jti='test', method=target_method, path=target_path, trace='trace-12345678')
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm='RS256')

    def call(self, method, path, *, changes=None, **kwargs):
        return self.client.request(method, path, headers={'X-Easyjob-Identity': self.token(path.split('?')[0], method, **(changes or {}))}, **kwargs)

    def test_context_usage_endpoints_pass_authenticated_owner(self):
        from app.services.context_usage import context_usage
        self.application.context_usage_status = AsyncMock(return_value=context_usage({'total_tokens': 1024}))
        for path, cid in (('/api/agent/context-usage', None),
                          ('/api/agent/conversations/101/context-usage', 101)):
            response = self.call('GET', path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data']['usedTokens'], 1024)
            args = self.application.context_usage_status.call_args.args
            self.assertEqual((args[0], args[1].user_id), (cid, 7))
            self.assertEqual(self.client.get(path).status_code, 401)
        self.application.context_usage_status.side_effect = HTTPException(404, '会话不存在或无权访问')
        self.assertEqual(self.call('GET', '/api/agent/conversations/102/context-usage').status_code, 404)

    def test_signed_identity_is_required_and_external_token_or_headers_do_not_work(self):
        path = '/api/agent/run-overview'
        for headers in ({}, {'X-User-Id':'7'}, {'X-Agent-Key':'secret','X-Agent-User':'7'},
                        {'Authorization':'Bearer '+self.token(path)}):
            self.assertEqual(self.client.get(path, headers=headers).status_code, 401)
        self.assertEqual(self.client.get(path, headers=[('X-Easyjob-Identity', self.token(path))]*2).status_code, 401)

    def test_wrong_issuer_audience_method_path_lifetime_and_session_rejected(self):
        path = '/api/agent/run-overview'
        for changes in ({'iss':'easyjob-blog'}, {'aud':'easyjob-blog'}, {'method':'POST'},
                        {'path':'/api/agent/memory'}, {'token_use':'delegation'}, {'kind':'anonymous'},
                        {'exp':int(time.time())-20}, {'exp':int(time.time())+120},
                        {'sub':'0'}, {'sid':'bad'}, {'ver':True}, {'iat':int(time.time())+60}):
            with self.subTest(changes=changes):
                self.assertEqual(self.call('GET', path, changes=changes).status_code, 401)

    def test_replaced_signature_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with patch.object(gateway, 'public_key', return_value=other.public_key()):
            self.assertEqual(self.call('GET', '/api/agent/run-overview').status_code, 401)

    def test_chat_uses_authenticated_user_and_camel_case_body(self):
        async def chat(request, principal):
            self.assertEqual((request.user_id, principal.user_id), (7,7))
            self.assertEqual(request.conversation_id, BIG)
            self.assertEqual(delegation.current_identity.get()['sid'], 'a'*64)
            return {'conversationId': BIG, 'reply': '中文', 'runId': RUN}
        self.application.chat = AsyncMock(side_effect=chat)
        response = self.call('POST', '/api/agent/chat', json={'conversationId':str(BIG), 'message':'你好','mode':'agent'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['conversationId'], str(BIG))
        self.assertEqual(response.json()['code'], 200)
        self.assertIsNone(delegation.current_identity.get())

    def test_user_identity_cannot_be_supplied_in_chat_body(self):
        self.application.chat = AsyncMock()
        for name in ('userId', 'user_id'):
            result = self.call('POST', '/api/agent/chat', json={'message':'hello',name:8})
            self.assertEqual(result.status_code, 422)
            self.assertNotIn('hello', result.text)
        self.application.chat.assert_not_awaited()

    def test_resume_preserves_approval_hash_and_request_identity(self):
        self.application.chat_resume = AsyncMock(return_value={'reply':'ok'})
        reply = self.call('POST','/api/agent/chat/resume',json={'conversationId':str(BIG),'action':'approve','runId':RUN,'draftHash':'c'*64})
        self.assertEqual(reply.status_code, 200)
        body, user = self.application.chat_resume.call_args.args
        self.assertEqual((body.draft_hash,body.user_id,user.user_id), ('c'*64,7,7))

    def test_metadata_filters_private_fields_and_preserves_large_ids(self):
        row = {'conversationId':BIG,'userId':7,'title':'标题','summary':'private summary','contextHash':'private'}
        self.application.list_conversations = AsyncMock(return_value={'data':[row]})
        self.application.get_conversation = AsyncMock(return_value={'data':row})
        for path in ('/api/agent/conversations','/api/agent/conversations/42'):
            response = self.call('GET',path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('private',response.text)
            self.assertIn('"'+str(BIG)+'"',response.text)

    def test_pagination_parameters_reach_application_without_precision_loss(self):
        self.application.get_messages = AsyncMock(return_value={'data':{'items':[],'beforeCursor':str(BIG)}})
        response = self.call('GET',f'/api/agent/conversations/42/messages?limit=30&before={BIG}')
        self.assertEqual(response.status_code,200)
        args=self.application.get_messages.call_args.args
        self.assertEqual((args[0],args[1],args[3],args[4]),(42,7,30,BIG))
        self.assertEqual(response.json()['data']['beforeCursor'], str(BIG))

    def test_business_error_and_validation_use_existing_envelope(self):
        self.application.cancel_chat=AsyncMock(side_effect=HTTPException(409,'运行状态已改变'))
        response=self.call('POST','/api/agent/chat/42/cancel')
        self.assertEqual((response.status_code,response.json()['code']), (409,409))
        self.assertEqual(self.call('GET','/api/agent/runs/not-a-uuid').status_code,422)
        self.application.cancel_chat.side_effect=RuntimeError('secret diagnostic')
        response=self.call('POST','/api/agent/chat/42/cancel')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('secret',response.text)

    def test_internal_endpoints_cannot_be_selected_by_browser(self):
        for path in ('/api/agent/internal/metrics','/api/agent/ServiceQuery','/api/agent/mcp/reload','/api/agent/health'):
            self.assertEqual(self.call('GET',path).status_code,404)

    def test_feature_operations_are_fixed_and_owner_scoped(self):
        with patch('app.services.service_queries.query',new_callable=AsyncMock,return_value=True) as query:
            response=self.call('POST',f'/api/agent/runs/{RUN}/delivery-metrics',json={'firstAnswerMs':123})
            self.assertEqual(response.status_code,200)
            q,uid=query.call_args.args
            self.assertEqual((q.kind,q.name,uid),('delivery_metrics',RUN,7))
            self.assertEqual(self.call('POST',f'/api/agent/runs/{RUN}/delivery-metrics',json={'firstAnswerMs':True}).status_code,422)
            query.reset_mock()
            for path, body in ((f'/api/agent/runs/{RUN}/delivery-metrics', {'firstAnswerMs': -1}),
                               (f'/api/agent/runs/{RUN}/delivery-metrics', {'firstAnswerMs': None}),
                               ('/api/agent/runs/bad/delivery-metrics', {'firstAnswerMs': 1})):
                self.assertEqual(self.call('POST', path, json=body).status_code, 422)
            query.assert_not_awaited()

    def test_memory_identity_and_validation_stay_at_the_public_python_boundary(self):
        self.application.memory_overview = AsyncMock(return_value={'memories': []})
        self.application.remove_memory_record = AsyncMock(return_value=True)
        self.assertEqual(self.call('GET', '/api/agent/memory?user_id=8').status_code, 200)
        self.assertEqual(self.application.memory_overview.call_args.args[-1].user_id, 7)
        self.application.memory_overview.reset_mock()
        for path in ('/api/agent/memory?limit=1000', '/api/agent/memory?kind=unknown',
                     '/api/agent/memory?before=0'):
            self.assertEqual(self.call('GET', path).status_code, 422)
        self.assertEqual(self.call('DELETE', '/api/agent/memory/records/19?version=invalid').status_code, 422)
        self.application.memory_overview.assert_not_awaited()
        self.application.remove_memory_record.assert_not_awaited()

    def test_stream_frames_remain_byte_compatible(self):
        async def source():
            yield 'data:__RUN_ID__:'+RUN+'\n\n'
            yield 'data:中文\n\n'
            yield 'data:[DONE]\n\n'
        @asynccontextmanager
        async def subscribe(identity):
            self.assertEqual(identity['user_id'],7)
            yield asyncio.Event()
        self.application.chat_stream=AsyncMock(return_value=StreamingResponse(source(),media_type='text/event-stream'))
        with patch.object(public_api.sessions,'subscribe',subscribe):
            reply=self.call('POST','/api/agent/chat/stream',json={'message':'hello'})
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.text,f'data:__RUN_ID__:{RUN}\n\ndata:中文\n\ndata:[DONE]\n\n')


class StreamSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_revocation_closes_following_and_finalizes_source(self):
        revoked,closed=asyncio.Event(),asyncio.Event()
        async def source():
            try:
                yield 'first'
                await asyncio.Event().wait()
            finally:
                closed.set()
        frames=guarded_frames(source(),revoked)
        self.assertEqual(await anext(frames),'first')
        next_frame=asyncio.create_task(anext(frames))
        await asyncio.sleep(0)
        revoked.set()
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(next_frame,1)
        self.assertTrue(closed.is_set())

    async def test_batch_checks_deduplicate_sessions_and_close_only_invalid(self):
        registry=StreamSessions()
        events=[asyncio.Event() for _ in range(3)]
        a={'user_id':7,'sid':'a'*64,'version':2}
        b={'user_id':8,'sid':'b'*64,'version':1}
        registry.entries={'1':(a,events[0]),'2':(a,events[1]),'3':(b,events[2])}
        registry.valid=AsyncMock(return_value={a['sid']:False,b['sid']:True})
        await registry.check()
        self.assertEqual(len(registry.valid.call_args.args[0]),2)
        self.assertEqual([e.is_set() for e in events],[True,True,False])

    async def test_logout_event_is_scoped_to_user_and_session(self):
        registry=StreamSessions()
        events=[asyncio.Event(),asyncio.Event()]
        registry.entries={'a':({'user_id':7,'sid':'a'},events[0]),'b':({'user_id':7,'sid':'b'},events[1])}
        registry.revoke({'userId':'7','sid':'a'})
        self.assertEqual([e.is_set() for e in events],[True,False])

    async def test_initial_session_failure_does_not_become_unauthorized(self):
        registry=StreamSessions()
        identity={'user_id':7,'sid':'a','version':0}
        for validity,status in ((None,503),({},401)):
            registry.valid=AsyncMock(return_value=validity)
            with self.assertRaises(HTTPException) as raised:
                async with registry.subscribe(identity):
                    self.fail('must reject before streaming')
            self.assertEqual(raised.exception.status_code,status)
            self.assertFalse(registry.entries)

    async def test_public_business_queries_do_not_inherit_private_user_routing(self):
        from app.rpc import blog_client
        token=delegation.current_identity.set({'user_id':7,'sid':'a'*64,'version':2})
        try:
            with patch.object(blog_client.settings,'AGENT_SERVICE_KEY','x'*32),patch.object(blog_client,'call',new_callable=AsyncMock,return_value=[]) as call:
                await blog_client.public_read('user_sources',ids=[7])
                identity=call.call_args.args[1].identity
                self.assertEqual(identity.user_id,1)
                self.assertEqual(identity.auth_session_id,'')
                self.assertEqual(blog_client.identity(7).auth_session_id,'a'*64)
                with self.assertRaises(blog_client.ServiceError):
                    blog_client.identity(8)
        finally:
            delegation.current_identity.reset(token)
