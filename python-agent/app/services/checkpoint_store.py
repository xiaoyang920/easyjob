"""Latest recovery state for new runs; existing full-history runs stay readable.

The 0.5.2 shallow saver keeps a thread-wide write registry. Filter it by
checkpoint ID before replay: writes from older steps are not pending work.
Keep the registry itself until terminal cleanup, including interrupt writes.
"""
from collections import OrderedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.checkpoint.redis.ashallow import AsyncShallowRedisSaver
from redis.asyncio import Redis


class ScopedShallowRedisSaver(AsyncShallowRedisSaver):
    async def _aload_pending_writes(self, thread_id, checkpoint_ns, checkpoint_id):
        if checkpoint_id is None:
            return []
        from langgraph.checkpoint.redis.util import to_storage_safe_str
        registry = f"write_keys_zset:{thread_id}:{to_storage_safe_str(checkpoint_ns)}:shallow"
        keys = await self._redis.zrange(registry, 0, -1)
        writes = {}
        # Bound pipeline size; do not silently drop errors or interrupt writes.
        for offset in range(0, len(keys), 200):
            pipeline = self._redis.pipeline(transaction=False)
            for key in keys[offset:offset + 200]:
                pipeline.json().get(key)
            for data in await pipeline.execute():
                if (data and data.get('thread_id') == thread_id
                        and data.get('checkpoint_ns') == checkpoint_ns
                        and data.get('checkpoint_id') == checkpoint_id):
                    writes[(data['task_id'], data['idx'])] = data
        return self._load_writes(self.serde, writes)


class LatestRunRedisSaver(BaseCheckpointSaver):
    """Route a whole run, including child namespaces, to one storage format.

    There is no destructive migration of live approvals. Legacy runs continue
    using their original saver until terminal retention deletes the thread.
    New runs keep one full state per namespace, with durable pending writes.
    """
    def __init__(self, redis_url=None, *, redis_client=None):
        self._owns_client = redis_client is None
        self.client = redis_client if redis_client is not None else Redis.from_url(redis_url)
        self.latest = ScopedShallowRedisSaver(redis_client=self.client)
        self.legacy = AsyncRedisSaver(redis_client=self.client)
        super().__init__(serde=self.latest.serde)
        self._routes = OrderedDict()

    async def __aenter__(self):
        try:
            await self.latest.__aenter__()
            await self.legacy.__aenter__()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        self._routes.clear()
        if self._owns_client:
            await self.client.aclose()

    async def _backend(self, config):
        thread_id = config['configurable']['thread_id']
        if thread_id in self._routes:
            self._routes.move_to_end(thread_id)
            return self._routes[thread_id]
        root_key = self.latest._make_shallow_redis_checkpoint_key(thread_id, '')
        if await self.client.exists(root_key):
            backend = self.latest
        else:
            root = await self.legacy.aget_tuple({'configurable': {'thread_id': thread_id, 'checkpoint_ns': ''}})
            backend = self.legacy if root is not None else self.latest
        self._routes[thread_id] = backend
        if len(self._routes) > 256:
            self._routes.popitem(last=False)
        return backend

    def get_next_version(self, current, channel):
        return self.legacy.get_next_version(current, channel)

    async def aget_tuple(self, config):
        return await (await self._backend(config)).aget_tuple(config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await (await self._backend(config)).aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=''):
        await (await self._backend(config)).aput_writes(config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        if not config or not config.get('configurable', {}).get('thread_id'):
            raise ValueError('Checkpoint listing requires a run thread')
        backend = await self._backend(config)
        async for item in backend.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def adelete_thread(self, thread_id):
        # The indexes include both formats. Delete legacy snapshots/registries
        # first, then shallow namespace keys and their write registries.
        await self.legacy.adelete_thread(thread_id)
        await self.latest.adelete_thread(thread_id)
        self._routes.pop(thread_id, None)
