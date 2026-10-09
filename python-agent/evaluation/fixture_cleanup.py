"""Remove only login sessions whose stored owner is an exact fixture user ID."""
from app.config import settings
from redis.asyncio import Redis

async def revoke_sessions(user_ids):
    owners={str(uid) for uid in user_ids}
    if not owners:return
    client=Redis(host=settings.REDIS_HOST,port=settings.REDIS_PORT,db=settings.REDIS_DB,password=settings.REDIS_PASSWORD or None,decode_responses=True)
    try:
        async for key in client.scan_iter(match='auth:session:*',count=100):
            value=await client.get(key)
            if value and value.split(':',1)[0] in owners:await client.delete(key)
    finally:await client.aclose()
