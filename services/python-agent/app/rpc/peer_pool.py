"""Bounded gRPC channel leases; idle/withdrawn peers drain before closing."""
import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class Entry:
    channel: object
    stub: object
    used: float
    active: int = 0
    retired: bool = False


class PeerPool:
    def __init__(self, factory, capacity=32, idle=300, clock=time.monotonic):
        if capacity < 1 or idle < 0:
            raise ValueError('Invalid RPC pool limits')
        self.factory, self.capacity, self.idle, self.clock = factory, capacity, idle, clock
        self.entries = {}
        self.closed = False

    def _retire(self, healthy=None):
        removed = []
        for target, entry in list(self.entries.items()):
            if healthy is not None and target not in healthy:
                entry.retired = True
            if not entry.active and (entry.retired or self.closed or self.clock() - entry.used >= self.idle):
                del self.entries[target]
                removed.append(entry)
        return removed

    async def _close(self, entries):
        if entries:
            # Finish all closes even when one waiter disconnects or a channel fails to close.
            await asyncio.shield(asyncio.gather(*(entry.channel.close() for entry in entries), return_exceptions=True))

    async def reconcile(self, healthy):
        await self._close(self._retire(set(healthy)))

    @asynccontextmanager
    async def lease(self, target, healthy):
        if self.closed:
            raise RuntimeError('RPC pool closed')
        removed = self._retire(set(healthy))
        entry = self.entries.get(target)
        if entry is None:
            if len(self.entries) >= self.capacity:
                idle = [(key, item) for key, item in self.entries.items() if not item.active]
                if not idle:
                    await self._close(removed)
                    raise RuntimeError('RPC endpoint pool busy')
                victim, old = min(idle, key=lambda item: item[1].used)
                del self.entries[victim]
                removed.append(old)
            try:
                channel, stub = self.factory(target)
            except BaseException:
                await self._close(removed)
                raise
            entry = self.entries[target] = Entry(channel, stub, self.clock())
        entry.active += 1
        entry.retired = False
        try:
            await self._close(removed)
            yield entry.stub
        finally:
            entry.active -= 1
            entry.used = self.clock()
            await self._close(self._retire())

    async def close(self):
        self.closed = True
        await self._close(self._retire(set()))
