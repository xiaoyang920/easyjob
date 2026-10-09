"""Bounded process-local query vectors; keys retain no query text or credentials."""
import asyncio
import hashlib
import math
import time
from collections import OrderedDict
from app.config import settings


class QueryVectorCache:
    def __init__(self, capacity=512, ttl=600, clock=time.monotonic):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self.values, self.inflight = OrderedDict(), {}
        self.hits = self.misses = self.coalesced = 0

    async def get_or_compute(self, namespace, text, dimensions, operation):
        if not self.capacity or len(text) > 4000:
            return await operation()
        key = hashlib.sha256((namespace + '\0' + str(dimensions) + '\0' + text).encode()).hexdigest()
        cached = self.values.get(key)
        if cached and cached[0] > self.clock():
            self.hits += 1
            self.values.move_to_end(key)
            return list(cached[1])
        self.values.pop(key, None)
        if key in self.inflight:
            self.coalesced += 1
            return list(await asyncio.shield(self.inflight[key]))
        self.misses += 1
        async def compute():
            try:
                vector = await operation()
                if (len(vector) == dimensions and all(isinstance(v, (int, float))
                        and not isinstance(v, bool) and math.isfinite(v) for v in vector)):
                    self.values[key] = (self.clock() + self.ttl, tuple(vector))
                    while len(self.values) > self.capacity:
                        self.values.popitem(last=False)
                return vector
            finally:
                self.inflight.pop(key, None)
        task = self.inflight[key] = asyncio.create_task(compute())
        # A cancelled waiter must not leave a failed background task unobserved.
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        return list(await asyncio.shield(task))


query_vector_cache = QueryVectorCache(settings.QUERY_VECTOR_CACHE_CAPACITY, settings.QUERY_VECTOR_CACHE_TTL_SECONDS)
