"""Deduplicated online session checks for public SSE subscribers, not executions."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.config import settings

log = logging.getLogger(__name__)


class StreamSessions:
    def __init__(self):
        self.entries = {}
        self.tasks = []
        self.client = None

    async def start(self):
        if self.tasks:
            return
        if len(settings.AUTH_SERVICE_CHECK_KEY.encode()) < 32:
            raise RuntimeError('Auth session check credential missing')
        self.client = httpx.AsyncClient(base_url=settings.AUTH_SERVICE_BASE_URL, timeout=2,
            headers={'X-Auth-Service-Key': settings.AUTH_SERVICE_CHECK_KEY}, trust_env=False)
        self.tasks = [asyncio.create_task(self.poll()), asyncio.create_task(self.listen())]

    async def valid(self, identities):
        try:
            response = await self.client.post('/internal/auth/session/batch', json=[
                {'userId': str(p['user_id']), 'sid': p['sid'], 'version': p['version']} for p in identities])
            response.raise_for_status()
            body = response.json()
            if body.get('code') == 200 and isinstance(body.get('data'), dict):
                return body['data']
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return None  # Distinguish unavailable authentication from an expired session.

    @asynccontextmanager
    async def subscribe(self, identity):
        key, revoked = uuid4().hex, asyncio.Event()
        self.entries[key] = (identity, revoked)
        try:
            # Covers revocation between gateway admission and subscriber registration.
            validity = await self.valid([identity])
            if validity is None:
                raise HTTPException(503, '认证服务暂不可用，请稍后重试')
            if validity.get(identity['sid']) is not True:
                raise HTTPException(401, '登录已失效，请重新登录')
            yield revoked
        finally:
            self.entries.pop(key, None)

    async def check(self):
        entries = list(self.entries.values())
        unique = {p['sid']: p for p, _ in entries}
        values = list(unique.values())
        for offset in range(0, len(values), 50):
            batch = values[offset:offset + 50]
            valid = await self.valid(batch) or {}
            ids = {p['sid'] for p in batch}
            for p, event in entries:
                if p['sid'] in ids and valid.get(p['sid']) is not True:
                    event.set()

    async def poll(self):
        while True:
            await asyncio.sleep(5)
            await self.check()

    def revoke(self, data):
        uid, sid = str(data.get('userId', '')), data.get('sid', '')
        for p, event in list(self.entries.values()):
            if str(p['user_id']) == uid and (not sid or sid == p['sid']):
                event.set()

    async def listen(self):
        from app.clients.redis_client import RedisClient
        redis = RedisClient().client
        try:
            while True:
                try:
                    async with redis.pubsub() as pubsub:
                        await pubsub.subscribe('easyjob:auth:revoke')
                        async for message in pubsub.listen():
                            if message['type'] == 'message':
                                data = json.loads(message['data'])
                                if isinstance(data, dict):
                                    self.revoke(data)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    log.warning('Session event listener reconnecting: %s', type(error).__name__)
                    await asyncio.sleep(2)
        finally:
            await redis.aclose()

    async def close(self):
        for _, event in self.entries.values():
            event.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        if self.client:
            await self.client.aclose()
            self.client = None


sessions = StreamSessions()


async def guarded_frames(source, revoked):
    """Stop following on revocation; the durable execution has its own lifecycle."""
    iterator = source.__aiter__()
    pending = None
    stop = asyncio.create_task(revoked.wait())
    try:
        while not revoked.is_set():
            pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait((pending, stop), return_when=asyncio.FIRST_COMPLETED)
            if stop in done:
                break
            try:
                frame = pending.result()
            except StopAsyncIteration:
                break
            pending = None
            if not revoked.is_set():
                yield frame
    finally:
        tasks = [t for t in (pending, stop) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(iterator, 'aclose'):
            await iterator.aclose()
