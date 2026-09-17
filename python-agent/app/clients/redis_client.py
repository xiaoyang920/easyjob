"""
Redis 客户端
对应 Java: RedisComponent.java
"""
import redis.asyncio as aioredis

from app.config import settings


class RedisClient:
    def __init__(self):
        # Upstash 等云 Redis 强制 TLS；本地 Docker/WSL Redis 无 TLS
        # 通过 REDIS_SSL 环境变量控制，默认根据 host 自动判断
        use_ssl = getattr(settings, "REDIS_SSL", None)
        if use_ssl is None:
            # 自动判断：host 里含 upstash / redis-cloud 等云服务关键字时启用 TLS
            host = (settings.REDIS_HOST or "").lower()
            use_ssl = any(k in host for k in ("upstash", "redis-cloud", "redislabs"))

        self.client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            ssl=use_ssl,
            decode_responses=True,
        )

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        await self.client.set(key, value, ex=ex)

    async def delete(self, key: str):
        await self.client.delete(key)
