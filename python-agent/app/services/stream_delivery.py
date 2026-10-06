"""Persist public SSE frames; HTTP readers do not own or cancel execution."""
import asyncio
import logging
from app.clients.mysql_client import db
from app.config import settings
from app.services.execution_admission import execution_admission
from app.services.run_repository import run_repository
from app.services.executor_heartbeat import maintain_executor

log = logging.getLogger(__name__)


class StreamDelivery:
    def __init__(self, database=db, admission=execution_admission, repository=run_repository):
        self.db, self.admission, self.repository = database, admission, repository
        self.tasks = {}
        self.cleanup_tasks = set()

    def start(self, rid, token, source, ticket=None, replay=False):
        key = (rid, token)
        if key in self.tasks:
            # A same-request replay can arrive after settlement but before the
            # first producer finishes writing its terminal frames.
            async def release_duplicate():
                await source.aclose()
                await self.admission.release(ticket)
            task = asyncio.create_task(release_duplicate())
            self.cleanup_tasks.add(task)
            def cleanup_done(completed):
                self.cleanup_tasks.discard(completed)
                if not completed.cancelled() and completed.exception():
                    log.error('重复订阅释放失败: run=%s', rid, exc_info=completed.exception())
            task.add_done_callback(cleanup_done)
            return
        async def produce():
            try:
                existing = await self.db.fetch_val('SELECT event_id FROM agent_stream_frame WHERE run_id=:rid AND execution_token=:token LIMIT 1',
                                                   {'rid': rid, 'token': token}) if replay else None
                if not existing:
                    config = {'configurable': {'run_id': rid, 'execution_token': token, 'replay': replay}}
                    async with maintain_executor(self.repository, config):
                        async for frame in source:
                            await self.append(rid, token, frame)
            except asyncio.CancelledError:
                await asyncio.shield(self.repository.fail(rid, token))
                raise
            except Exception:
                log.exception('流式执行或事件持久化失败: run=%s', rid)
                await self.repository.fail(rid, token)
                try:
                    await self.append(rid, token, 'data:[ERROR] 运行中断，请查询会话结果\n\n')
                    await self.append(rid, token, 'data:[DONE]\n\n')
                except Exception: log.exception('终止事件保存失败: run=%s', rid)
            finally:
                await source.aclose()
                await asyncio.shield(self.admission.release(ticket))
                self.tasks.pop(key, None)
        self.tasks[key] = asyncio.create_task(produce(), name=f'agent-stream-{rid}')

    async def append(self, rid, token, frame):
        return await self.db.execute('''INSERT INTO agent_stream_frame (run_id,execution_token,data)
            VALUES (:rid,:token,:data)''', {'rid': rid, 'token': token, 'data': frame})

    async def follow(self, rid, token, after=0):
        idle = 0
        while True:
            rows = await self.db.fetch_all('''SELECT event_id,data FROM agent_stream_frame
                WHERE run_id=:rid AND execution_token=:token AND event_id>:after ORDER BY event_id LIMIT 100''',
                {'rid': rid, 'token': token, 'after': after})
            for row in rows:
                after = int(row._mapping['event_id'])
                frame = row._mapping['data']
                yield f'id:{after}\n' + frame
                # Java's legacy Flux<String> adapter strips SSE metadata. A data
                # cursor AFTER the payload retains compatibility and safe replay.
                yield f'data:__EVENT_ID__:{after}\n\n'
                if frame == 'data:[DONE]\n\n': return
            if rows:
                idle = 0
                continue
            idle += 1
            run = await self.repository.get(rid)
            if not run or run['execution_token'] != token:
                yield 'data:[ERROR] 运行已变更，请重新加载会话\n\ndata:[DONE]\n\n'
                return
            from datetime import datetime
            expired = run['status'] == 'running' and (run['deadline'] <= datetime.utcnow()
                or run.get('executor_lease_until') is not None and run['executor_lease_until'] <= datetime.utcnow())
            if expired:
                await self.repository.expire_existing(run['conversation_id'], run['user_id'], rid)
                run = await self.repository.get(rid)
            if (expired or run['status'] != 'running') and (rid, token) not in self.tasks and idle >= 8:
                # Handles server restart, retention expiry and persistence failure.
                # Completed content remains authoritative in result_json/history.
                import json
                result = json.loads(run.get('result_json') or '{}')
                if result.get('interrupted'):
                    yield 'data:__INTERRUPTED__:' + json.dumps(result['interrupted'], ensure_ascii=False) + '\n\n'
                elif result.get('reply'):
                    for marker, value in [('__ARTICLES__:', result.get('articles', [])), ('__CITATIONS__:', result.get('citations', [])),
                                          ('__REPLY__:', {'content': result['reply']})]:
                        yield 'data:' + marker + json.dumps(value, ensure_ascii=False) + '\n\n'
                    if result.get('draft_article_id'):
                        yield 'data:__DRAFT_SAVED__:' + json.dumps({'draftArticleId': str(result['draft_article_id']), 'title': ''}) + '\n\n'
                    yield 'data:__PROGRESS__:done\n\n'
                else:
                    yield 'data:[ERROR] 运行已中断，请重新发起请求\n\n'
                yield 'data:[DONE]\n\n'
                return
            if idle % 40 == 0: yield ': keepalive\n\n'
            await asyncio.sleep(.25)

    async def shutdown(self):
        tasks = [*self.tasks.values(), *self.cleanup_tasks]
        if not tasks: return
        _, pending = await asyncio.wait(tasks, timeout=5)
        for task in pending: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


stream_delivery = StreamDelivery()
