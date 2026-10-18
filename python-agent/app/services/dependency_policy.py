"""Bounded read-only retries, concurrency and a process-local circuit per provider."""
import asyncio
from time import monotonic
import httpx
from zhipuai import APIConnectionError as ZhipuConnectionError


class DependencyUnavailable(ConnectionError):
    pass


class DependencyHTTPError(ConnectionError):
    def __init__(self, status):
        self.status_code = status
        super().__init__('External service rejected the request')


def transient(error):
    code = getattr(error, 'status_code', None) or getattr(getattr(error, 'response', None), 'status_code', None)
    return code in (408, 429) or isinstance(code, int) and 500 <= code < 600 or (
        code is None and isinstance(error, (TimeoutError, httpx.RequestError, ConnectionError, ZhipuConnectionError)))


class DependencyPolicy:
    def __init__(self, name, *, timeout=20, concurrency=4, attempts=2, threshold=3, cooldown=30, clock=monotonic):
        self.name, self.timeout, self.attempts = name, timeout, attempts
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self.slots = asyncio.Semaphore(concurrency)
        self.failures, self.opened_at, self.probing = 0, None, False

    def _admit(self):
        if self.opened_at is None: return False
        if self.clock() - self.opened_at < self.cooldown or self.probing:
            raise DependencyUnavailable(self.name + '暂时熔断，请稍后重试')
        self.probing = True
        return True

    async def run(self, operation):
        probe = self._admit()
        async def bounded():
            async with self.slots:
                if not probe and self.opened_at is not None:
                    raise DependencyUnavailable(self.name + '暂时熔断，请稍后重试')
                for attempt in range(1 if probe else self.attempts):
                    try: return await operation()
                    except Exception as exc:
                        if not transient(exc) or attempt + 1 >= (1 if probe else self.attempts): raise
                        await asyncio.sleep(.25 * (2 ** attempt))
        try:
            result = await asyncio.wait_for(bounded(), self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not isinstance(exc, DependencyUnavailable) and (transient(exc) or probe):
                self.failures += 1
                if probe or self.failures >= self.threshold: self.opened_at = self.clock()
            raise
        else:
            self.failures, self.opened_at = 0, None
            return result
        finally:
            if probe: self.probing = False


web_policy = DependencyPolicy('联网搜索', timeout=16)
fetch_policy = DependencyPolicy('网页抓取', timeout=8, concurrency=2)
rerank_policy = DependencyPolicy('精排服务', timeout=18)
embedding_policy = DependencyPolicy('向量服务', timeout=20)
