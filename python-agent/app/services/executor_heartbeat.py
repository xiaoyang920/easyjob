"""Keep an executing run alive independently of HTTP/SSE subscribers."""
import asyncio
import logging
from contextlib import asynccontextmanager
from app.config import settings
from fastapi import HTTPException

log = logging.getLogger(__name__)


@asynccontextmanager
async def maintain_executor(repository, config):
    cfg = config['configurable']
    if cfg.get('replay'):
        yield
        return
    owner = asyncio.current_task()
    async def pulse():
        while True:
            await asyncio.sleep(settings.EXECUTOR_HEARTBEAT_SECONDS)
            try:
                await asyncio.wait_for(repository.renew_executor(cfg['run_id'], cfg['execution_token']), 5)
            except Exception as error:
                # Settlement ends execution, but delivery may still be writing terminal frames.
                if isinstance(error, HTTPException) and error.status_code == 409 and hasattr(repository, 'get'):
                    try:
                        run = await asyncio.wait_for(repository.get(cfg['run_id']), 5)
                        if run and run['execution_token'] == cfg['execution_token'] and run['status'] in ('succeeded', 'awaiting_approval'):
                            return
                    except Exception:
                        pass
                log.exception('执行心跳丢失，停止旧执行器: run=%s', cfg['run_id'])
                owner.cancel()
                return
    heartbeat = asyncio.create_task(pulse(), name=f"heartbeat-{cfg['run_id']}")
    try:
        yield
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
