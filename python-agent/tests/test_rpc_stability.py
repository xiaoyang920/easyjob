import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.rpc.peer_pool import PeerPool
from app.rpc.discovery import Catalog


class RpcStabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_hundred_endpoint_replacements_reclaim_channels(self):
        closed = []
        def factory(target):
            async def close(): closed.append(target)
            return SimpleNamespace(close=close), target
        pool = PeerPool(factory, capacity=4)
        for i in range(100):
            target = f'peer:{i}'
            async with pool.lease(target, [target]) as stub:
                self.assertEqual(stub, target)
            self.assertLessEqual(len(pool.entries), 1)
        await pool.close()
        self.assertEqual(len(closed), 100)
        self.assertEqual(len(set(closed)), 100)

    async def test_withdrawal_does_not_close_active_call_and_cancellation_releases(self):
        channel = SimpleNamespace(close=AsyncMock())
        pool = PeerPool(lambda target: (channel, target))
        entered = asyncio.Event()
        async def slow():
            async with pool.lease('old', ['old']):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(slow());await entered.wait()
        await pool.reconcile([]);channel.close.assert_not_awaited()
        task.cancel();await asyncio.gather(task, return_exceptions=True)
        channel.close.assert_awaited_once();self.assertFalse(pool.entries)

    async def test_capacity_evicts_idle_and_refuses_to_interrupt_active_calls(self):
        closed = []
        def factory(target):
            async def close(): closed.append(target)
            return SimpleNamespace(close=close), target
        pool = PeerPool(factory, capacity=1)
        async with pool.lease('a', ['a', 'b']):
            with self.assertRaises(RuntimeError):
                async with pool.lease('b', ['a', 'b']): pass
        async with pool.lease('b', ['a', 'b']): pass
        self.assertEqual(closed, ['a']);await pool.close()

    async def test_slow_registry_refresh_never_blocks_snapshot_readers(self):
        catalog = Catalog();catalog.peers = ('peer:1',)
        import time
        catalog.refreshed = time.monotonic()
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(*args):
            started.set();await release.wait()
            return SimpleNamespace(json=lambda: [])
        catalog.http = slow
        task = asyncio.create_task(catalog.refresh());await started.wait()
        try:
            results = await asyncio.wait_for(asyncio.gather(*(catalog.target(i) for i in range(1000))), 1)
            self.assertEqual(set(results), {'peer:1'})
        finally:
            release.set();await task
        with self.assertRaises(RuntimeError): await catalog.target(1)
