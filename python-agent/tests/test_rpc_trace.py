import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.rpc import server, blog_client
from app.rpc.generated import easyjob_rpc_pb2 as pb
from app.services.logging_config import current_trace_id, request_trace, set_request_trace


class RpcTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_bidirectional_identity_preserves_trace_and_concurrent_contexts_are_isolated(self):
        seen = []
        async def cancel(*args):
            await asyncio.sleep(0)
            seen.append(blog_client.identity(7).trace_id)
            return {'ok': True}
        key = 'trace-test-service-key-32-bytes-long'
        service = server.AgentRpc(SimpleNamespace(cancel_chat=cancel))
        with patch.object(server.settings, 'AGENT_SERVICE_KEY', key):
            await asyncio.gather(*(service.Cancel(pb.ConversationRequest(
                identity=pb.Identity(user_id=7, service_key=key, trace_id=f'trace-{i:08}'), conversation_id=1), None)
                for i in range(50)))
        self.assertEqual(set(seen), {f'trace-{i:08}' for i in range(50)})
        self.assertEqual(current_trace_id(), '-')

    async def test_run_logging_retains_incoming_trace_and_invalid_ids_are_replaced(self):
        with request_trace(1, 'trusted-12345678'):
            set_request_trace(2)
            self.assertEqual(current_trace_id(), 'trusted-12345678')
            with request_trace(1, 'bad\nsecret'):
                self.assertNotIn('secret', current_trace_id())
            self.assertEqual(current_trace_id(), 'trusted-12345678')
        self.assertEqual(current_trace_id(), '-')
