"""Restart readiness only retries authenticated reads, and has a hard deadline."""
import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
import httpx

spec = importlib.util.spec_from_file_location('rpc_ready_script',
    Path(__file__).resolve().parents[2] / 'scripts/agent-rpc-ready.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def ready():
    return httpx.Response(200, json={'status': 'ready', 'rpc': 'ok'})


class RpcReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_connection_then_two_successes(self):
        client = AsyncMock()
        client.get.side_effect = [httpx.Response(502), ready(), ready()]
        result = await probe.wait_ready(client, timeout=1, interval=0)
        self.assertEqual(result, {'status': 'ready', 'attempts': 3, 'failed_probes': 1})
        for call in client.get.call_args_list:
            self.assertEqual(call.args, ('/internal/agent/ready',))
        client.post.assert_not_called()

    async def test_wrong_key_or_missing_endpoint_stops_immediately(self):
        for status in (401, 403, 404):
            client = AsyncMock()
            client.get.return_value = httpx.Response(status)
            result = await probe.wait_ready(client, timeout=1, interval=0)
            self.assertEqual(result['reason'], 'configuration')
            self.assertEqual(client.get.call_count, 1)

    async def test_interrupted_success_sequence_starts_over(self):
        client = AsyncMock()
        client.get.side_effect = [ready(), httpx.ConnectError('down'), ready(), ready()]
        result = await probe.wait_ready(client, timeout=1, interval=0)
        self.assertEqual(result['attempts'], 4)

    async def test_generic_http_health_is_not_rpc_readiness(self):
        client = AsyncMock()
        client.get.side_effect = [httpx.Response(200, json={'status': 'ok'}), ready(), ready()]
        self.assertEqual((await probe.wait_ready(client, timeout=1, interval=0))['failed_probes'], 1)

    async def test_hanging_probe_cannot_exceed_overall_deadline(self):
        async def hang(*args):
            await asyncio.sleep(10)
        client = AsyncMock()
        client.get.side_effect = hang
        result = await asyncio.wait_for(probe.wait_ready(client, timeout=.02, interval=0), .5)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'deadline')
