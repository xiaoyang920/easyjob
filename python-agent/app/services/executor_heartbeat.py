"""Keep an executing run alive independently of HTTP/SSE subscribers."""
import asyncio
import logging
from contextlib import asynccontextmanager
from app.config import settings
from fastapi import HTTPException

log = logging.getLogger(__name__)

# Execution belongs to the application, not to an SSE subscriber. Explicit
# cancellation is applied only after the database has fenced the owned run.
_executors = {}


def cancel_local_run(run_id):
    owners = {owner for (rid, _), tasks in list(_executors.items()) if rid == run_id for owner in tasks}
    current = asyncio.current_task()
    for owner in owners:
        if owner is not current and not owner.done() and not owner.cancelling():
            owner.cancel('user_stop')


@asynccontextmanager
async def maintain_executor(repository, config):
    cfg = config['configurable']
    if cfg.get('replay'):
        yield
        return
    owner = asyncio.current_task()
    key = (cfg['run_id'], cfg['execution_token'])
    owners = _executors.setdefault(key, {})
    owners[owner] = owners.get(owner, 0) + 1
    async def pulse():
        while True:
            await asyncio.sleep(settings.EXECUTOR_HEARTBEAT_SECONDS)
            try:
                await asyncio.wait_for(repository.renew_executor(cfg['run_id'], cfg['execution_token']), 5)
                from app.services.run_metrics import metrics_from
                metrics = metrics_from(config)
                if metrics and hasattr(repository, 'persist_metrics'):
                    await asyncio.wait_for(repository.persist_metrics(cfg['run_id'], cfg['execution_token'], metrics), 5)
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
        try:
            await asyncio.gather(heartbeat, return_exceptions=True)
        finally:
            owners[owner] -= 1
            if not owners[owner]:
                owners.pop(owner)
            if not owners:
                _executors.pop(key, None)
