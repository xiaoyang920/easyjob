"""Dependency readiness, bounded operational aggregates and public-frame retention."""
import asyncio
import json
import math
from time import monotonic
from redis.asyncio import Redis
from elasticsearch import AsyncElasticsearch
from app.clients.mysql_client import db
from app.clients.redis_client import RedisClient
from app.config import settings


def latency_distribution(values):
    values = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0)
    return {'count': len(values), 'p50_ms': values[math.ceil(len(values) * .5) - 1] if values else None,
            'p95_ms': values[math.ceil(len(values) * .95) - 1] if values else None}


class Operations:
    def __init__(self, database=db):
        self.db = database
        self.cached = None
        self.checked_at = 0
        self.cleanup_at = 0
        self.expiry_at = 0
        self.lock = asyncio.Lock()

    async def probe_sql(self):
        await self.db.fetch_val('SELECT 1')

    async def probe_redis(self):
        client = RedisClient().client
        try: await client.ping()
        finally: await client.aclose()

    async def probe_checkpoint(self):
        client = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT,
                       db=settings.REDIS_STACK_DB, password=settings.REDIS_STACK_PASSWORD or None)
        try:
            await client.ping()
            # A plain Redis ping is not enough for RedisSaver's JSON/search indexes.
            await client.execute_command('FT.INFO', 'checkpoint')
            await client.execute_command('FT.INFO', 'checkpoint_write')
            await client.execute_command('JSON.TYPE', 'easyjob:readiness:nonexistent')
        finally: await client.aclose()

    async def probe_es(self):
        client = AsyncElasticsearch(f'http://{settings.ES_HOST}:{settings.ES_PORT}', request_timeout=2, max_retries=0)
        try:
            if not await client.ping(): raise ConnectionError('unavailable')
        finally: await client.close()

    async def readiness(self):
        async with self.lock:
            if self.cached and monotonic() - self.checked_at < 5: return self.cached
            async def check(name, probe):
                try:
                    await asyncio.wait_for(probe(), 2)
                    return name, 'up'
                except Exception: return name, 'down'
            states = dict(await asyncio.gather(*(check(name, probe) for name, probe in
                [('mysql', self.probe_sql), ('redis', self.probe_redis),
                 ('checkpoint', self.probe_checkpoint), ('elasticsearch', self.probe_es)])))
            self.cached = {'status': 'ready' if all(v == 'up' for v in states.values()) else 'unready', 'dependencies': states}
            self.checked_at = monotonic()
            return self.cached

    async def metrics(self):
        result = {}
        for name, table in [('runs', 'agent_run'), ('memory_jobs', 'agent_background_job')]:
            rows = await self.db.fetch_all(f'SELECT status,COUNT(*) AS count FROM {table} GROUP BY status')
            result[name] = {r._mapping['status']: r._mapping['count'] for r in rows}
        rows = await self.db.fetch_all("""SELECT state,COUNT(*) AS count FROM agent_execution_lease
            WHERE expires_at>UTC_TIMESTAMP(6) GROUP BY state""")
        result['admission'] = {r._mapping['state']: r._mapping['count'] for r in rows}
        result['limits'] = {'global': settings.EXECUTION_GLOBAL_LIMIT, 'per_user': settings.EXECUTION_USER_LIMIT,
                            'queue': settings.EXECUTION_QUEUE_LIMIT, 'wait_seconds': settings.EXECUTION_WAIT_SECONDS,
                            'run_tokens': settings.RUN_TOTAL_TOKEN_BUDGET}
        for name, table in [('memory_oldest_pending_seconds', 'agent_background_job')]:
            result[name] = await self.db.fetch_val(f"""SELECT COALESCE(MAX(TIMESTAMPDIFF(SECOND,created_at,UTC_TIMESTAMP(6))),0)
                FROM {table} WHERE status IN ('pending','dispatched','running')""")
        from app.rpc.blog_client import maintenance
        try:
            blog = await maintenance('metrics')
            result['article_jobs'] = {r['status']: r['count'] for r in blog['article_jobs']}
            result['article_oldest_pending_seconds'] = blog['article_oldest_pending_seconds']
        except Exception:
            result['article_jobs'] = None
            result['article_oldest_pending_seconds'] = None
        result['recent_quality'] = await self.recent_quality()
        return result

    async def recent_quality(self):
        rows = await self.db.fetch_all("""SELECT status,JSON_EXTRACT(result_json,'$.metrics') AS metrics FROM agent_run
            WHERE created_at>=TIMESTAMPADD(HOUR,-24,NOW(6)) ORDER BY created_at DESC LIMIT 2001""")
        sampled = rows[:2000]
        measured = [json.loads(r._mapping['metrics']) if isinstance(r._mapping['metrics'], str) else r._mapping['metrics']
                    for r in sampled if r._mapping['metrics'] not in (None, 'null')]
        measured = [m for m in measured if isinstance(m, dict)]
        calls = sum(m.get('llm_calls', 0) for m in measured)
        failures = sum(m.get('failed_llm_calls', 0) for m in measured)
        events = await self.db.fetch_all("""SELECT e.node,e.status,e.duration_ms FROM agent_run_event e
            JOIN agent_run r ON r.run_id=e.run_id WHERE r.created_at>=TIMESTAMPADD(HOUR,-24,NOW(6))
            AND e.status<>'started' ORDER BY e.event_id DESC LIMIT 10001""")
        stages, degraded, rerank_calls, approval_conflicts = {}, 0, 0, 0
        known = {'main_agent', 'main_retrieve', 'main_delegate', 'prepare_draft', 'collect_draft', 'final_gate',
                 'generate_draft', 'approve_draft', 'save_draft', 'reject_draft', 'approval'}
        for row in events[:10000]:
            r = row._mapping
            name = r['node'] if r['node'] in ('retrieval/query_rewrite', 'retrieval/coarse_retrieval', 'retrieval/rerank',
                'retrieval/web_search', 'retrieval/evidence_verification') else r['node'].rsplit('.', 1)[-1]
            if name not in known and not name.startswith('retrieval/'):
                name = 'task'
            stage = stages.setdefault(name, {'durations': [], 'failed': 0})
            if r['duration_ms'] is not None: stage['durations'].append(r['duration_ms'])
            stage['failed'] += r['status'] == 'failed'
            if name == 'retrieval/rerank':
                rerank_calls += 1
                degraded += r['status'] == 'degraded'
            approval_conflicts += name == 'approval' and r['status'] == 'conflict'
        from app.services.query_vector_cache import query_vector_cache
        return {'query_vector_cache': {'scope': 'current process since startup',
                    'hits': query_vector_cache.hits, 'misses': query_vector_cache.misses,
                    'coalesced': query_vector_cache.coalesced, 'entries': len(query_vector_cache.values)},
                'window_hours': 24, 'sampled_runs': len(sampled), 'runs_truncated': len(rows) > 2000,
                'events_truncated': len(events) > 10000, 'runs_with_metrics': len(measured),
                'model_calls': calls, 'observed_model_failures': failures,
                'model_failure_rate': failures / calls if calls and all('failed_llm_calls' in m for m in measured) else None,
                'measured_input_tokens': sum(m.get('measured_input_tokens', 0) for m in measured),
                'measured_output_tokens': sum(m.get('measured_output_tokens', 0) for m in measured),
                'runs_with_complete_usage': sum(bool(m.get('token_usage_complete')) for m in measured),
                'rerank_calls': rerank_calls, 'rerank_degraded': degraded,
                'rerank_degraded_rate': degraded / rerank_calls if rerank_calls else None,
                'approval_conflicts': approval_conflicts,
                'stages': {name: {**latency_distribution(v['durations']), 'failed': v['failed']} for name, v in stages.items()},
                'scope': 'bounded persisted samples; terminal failure metrics may be missing; stage durations exclude approval wait'}

    async def cleanup(self):
        from app.services.draft_commit import reconcile
        await reconcile(self.db)
        if not self.expiry_at or monotonic() - self.expiry_at >= 10:
            from app.services.run_repository import RunRepository
            from fastapi import HTTPException
            expired = await self.db.fetch_all("""SELECT r.run_id,r.user_id,r.conversation_id FROM agent_run r
                JOIN ai_conversation c ON c.conversation_id=r.conversation_id AND c.user_id=r.user_id AND c.status=1
                WHERE r.status IN ('running','awaiting_approval') AND
                (r.deadline<=UTC_TIMESTAMP(6) OR (r.status='running' AND r.executor_lease_until<=UTC_TIMESTAMP(6)))
                AND r.draft_article_id IS NULL ORDER BY r.deadline LIMIT 100""")
            repository = RunRepository(self.db)
            for row in expired:
                r = row._mapping
                try:
                    await repository.expire_existing(r['conversation_id'], r['user_id'], r['run_id'])
                except HTTPException as exc:
                    if exc.status_code != 404: raise
            self.expiry_at = monotonic()
        if self.cleanup_at and monotonic() - self.cleanup_at < 60: return
        from app.services.durable_jobs import DurableJobs
        from app.services.checkpoint_retention import EXPIRED_CHECKPOINT_SQL, CHECKPOINT_CLEANUP_KEY_SQL, retention_parameters
        old_runs = await self.db.fetch_all(f"""SELECT r.run_id,r.user_id,r.conversation_id,
            {CHECKPOINT_CLEANUP_KEY_SQL} AS cleanup_key FROM agent_run r
            LEFT JOIN agent_background_job j ON j.job_id=SHA2({CHECKPOINT_CLEANUP_KEY_SQL},256)
            WHERE {EXPIRED_CHECKPOINT_SQL} AND j.job_id IS NULL
            ORDER BY r.updated_at LIMIT 100""", retention_parameters())
        for row in old_runs:
            r = row._mapping
            await DurableJobs(self.db).enqueue(r['cleanup_key'], 'checkpoint_cleanup',
                r['user_id'], r['conversation_id'], {'run_id': r['run_id']})
        # Each delete rechecks eligibility; an admin retry between SELECT and DELETE is preserved.
        started=monotonic()
        for batch in range(4):
            if monotonic()-started>4:break
            frames=await self.db.fetch_all("""SELECT f.event_id FROM agent_stream_frame f
                JOIN agent_run r ON r.run_id=f.run_id WHERE f.created_at<TIMESTAMPADD(DAY,-:days,UTC_TIMESTAMP(6))
                AND r.status NOT IN ('running','awaiting_approval') ORDER BY f.event_id LIMIT 500""",{'days':settings.STREAM_RETENTION_DAYS})
            if frames:
                args={'days':settings.STREAM_RETENTION_DAYS,**{f'f{i}':r._mapping['event_id'] for i,r in enumerate(frames)}}
                keys=','.join(f':f{i}' for i in range(len(frames)))
                await self.db.execute(f"""DELETE f FROM agent_stream_frame f JOIN agent_run r ON r.run_id=f.run_id
                    WHERE f.event_id IN ({keys}) AND r.status NOT IN ('running','awaiting_approval')
                    AND f.created_at<TIMESTAMPADD(DAY,-:days,UTC_TIMESTAMP(6))""",args)
            sizes=[len(frames)]
            for table in ('agent_background_job',):
                eligible="(status='completed' AND updated_at<TIMESTAMPADD(DAY,-30,UTC_TIMESTAMP(6))) OR (status='dead' AND updated_at<TIMESTAMPADD(DAY,-90,UTC_TIMESTAMP(6)))"
                rows=await self.db.fetch_all(f'SELECT job_id FROM {table} WHERE {eligible} LIMIT 500')
                sizes.append(len(rows))
                if rows:
                    args={f'j{i}':r._mapping['job_id'] for i,r in enumerate(rows)}
                    keys=','.join(f':j{i}' for i in range(len(rows)))
                    await self.db.execute(f'DELETE FROM {table} WHERE job_id IN ({keys}) AND ({eligible})',args)
            if max(sizes)<500:break
        from app.rpc.blog_client import maintenance
        await maintenance('cleanup')
        self.cleanup_at = monotonic()


operations = Operations()
