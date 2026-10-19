"""MySQL-backed, leased jobs. Remote operations are at-least-once and idempotent."""
import asyncio
import hashlib
import json
import logging
from uuid import uuid4

from app.clients.mysql_client import db
from app.config import settings

log = logging.getLogger(__name__)


class LeaseLost(RuntimeError):
    pass


class DurableJobs:
    LEASE_SECONDS = 120

    def __init__(self, database=db):
        self.db = database

    async def enqueue(self, key, kind, uid, cid, payload):
        job_id = hashlib.sha256(key.encode()).hexdigest()
        await self.db.execute("""INSERT IGNORE INTO agent_background_job
            (job_id,kind,user_id,conversation_id,payload,available_at,created_at,updated_at)
            VALUES (:id,:kind,:uid,:cid,:payload,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
            {"id": job_id, "kind": kind, "uid": uid, "cid": cid, "payload": json.dumps(payload, ensure_ascii=False)})
        return job_id

    async def enqueue_extraction(self, uid, cid, message_id):
        # Retired API: no new extraction work, including callers from old checkpoints.
        return None

    async def claim(self):
        # Candidate discovery is nonlocking. Lock only existing primary-key rows;
        # SKIP LOCKED allows other workers to claim different jobs without tail-gap locks.
        candidates = await self.db.fetch_all("""SELECT job_id FROM agent_background_job WHERE
            (status='pending' AND available_at<=UTC_TIMESTAMP(6)) OR
            (status='running' AND lease_until<=UTC_TIMESTAMP(6))
            ORDER BY available_at,created_at LIMIT 16""")
        for candidate in candidates:
            async with self.db.transaction():
                row = await self.db.fetch_one("""SELECT *,
                    ((status='pending' AND available_at<=UTC_TIMESTAMP(6)) OR
                     (status='running' AND lease_until<=UTC_TIMESTAMP(6))) AS eligible
                    FROM agent_background_job WHERE job_id=:id FOR UPDATE SKIP LOCKED""",
                    {"id": candidate._mapping["job_id"]})
                if not row or not row._mapping['eligible']: continue
                job = dict(row._mapping)
                if job['attempts'] >= settings.BACKGROUND_JOB_MAX_ATTEMPTS:
                    await self.db.execute("""UPDATE agent_background_job SET status='dead',lease_until=NULL,
                        last_error='attempts_exhausted',updated_at=UTC_TIMESTAMP(6) WHERE job_id=:id""", {'id': job['job_id']})
                    continue
                token = str(uuid4())
                await self.db.execute("""UPDATE agent_background_job SET status='running',attempts=attempts+1,
                    lease_token=:token,lease_until=TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)),updated_at=UTC_TIMESTAMP(6) WHERE job_id=:id""",
                    {"id": job["job_id"], "token": token, "ttl": self.LEASE_SECONDS})
                job.update(lease_token=token, attempts=job["attempts"] + 1)
                job["payload"] = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
                return job
        return None

    async def assert_lease(self, job):
        row = await self.db.fetch_one("""SELECT job_id FROM agent_background_job WHERE job_id=:id
            AND status='running' AND lease_token=:token AND lease_until>UTC_TIMESTAMP(6) FOR UPDATE""",
            {"id": job["job_id"], "token": job["lease_token"]})
        if not row:
            raise LeaseLost("background job lease is no longer valid")

    async def complete(self, job):
        await self.db.execute("""UPDATE agent_background_job SET status='completed',lease_until=NULL,last_error=NULL,updated_at=UTC_TIMESTAMP(6)
            WHERE job_id=:id AND status='running' AND lease_token=:token AND lease_until>UTC_TIMESTAMP(6)""",
            {"id": job["job_id"], "token": job["lease_token"]})

    async def retry(self, job, error):
        await self.db.execute("""UPDATE agent_background_job SET status=:status,lease_until=NULL,
            available_at=TIMESTAMPADD(SECOND,:delay,UTC_TIMESTAMP(6)),last_error=:error,updated_at=UTC_TIMESTAMP(6)
            WHERE job_id=:id AND status='running' AND lease_token=:token AND lease_until>UTC_TIMESTAMP(6)""",
            {"id": job["job_id"], "token": job["lease_token"], "status": "dead" if job["attempts"] >= settings.BACKGROUND_JOB_MAX_ATTEMPTS else "pending",
             "delay": min(300, 5 * 2 ** (job["attempts"] - 1)), "error": type(error).__name__[:128]})


class BackgroundWorker:
    def __init__(self, jobs=None):
        self.jobs = jobs or DurableJobs()
        self.task = None
        self.stop_event = asyncio.Event()

    async def handle(self, job):
        from app.services.memory import memory_service
        uid, cid = job["user_id"], job["conversation_id"]
        if job["kind"] == "memory_extract":
            # Drain old durable jobs without reading history or calling a model.
            return
        elif job['kind'] == 'memory_write':
            from app.services.memory_policy import MemoryPolicyService
            await MemoryPolicyService(self.jobs.db).process_write(job)
        elif job['kind'] == 'checkpoint_cleanup':
            rid = str(job['payload'].get('run_id', ''))
            from uuid import UUID
            UUID(rid)
            from app.services.checkpoint_retention import EXPIRED_CHECKPOINT_SQL, retention_parameters
            # Serialize deletion with claim_recovery/claim_resume on this row.
            # A mere pre-delete check leaves a race where a resumed run is erased.
            async with self.jobs.db.transaction():
                row = await self.jobs.db.fetch_one(f"""SELECT r.run_id FROM agent_run r
                    WHERE r.run_id=:rid AND r.user_id=:uid AND r.conversation_id=:cid
                    AND {EXPIRED_CHECKPOINT_SQL} FOR UPDATE""",
                    {'rid': rid, 'uid': uid, 'cid': cid, **retention_parameters()})
                if row:
                    from app.graph.builder import get_graph
                    graph = await get_graph()
                    await asyncio.wait_for(graph.checkpointer.adelete_thread('run_' + rid), 30)
        elif job["kind"] == "memory_index":
            ids = job["payload"]["ids"]
            if ids:
                params = {"uid": uid, **{f"m{i}": mid for i, mid in enumerate(ids)}}
                placeholders = ','.join(f":m{i}" for i in range(len(ids)))
                rows = await self.jobs.db.fetch_all(f"""SELECT memory_id,content,importance,memory_type,scope,scope_conversation_id
                    FROM user_memory WHERE user_id=:uid AND status='active' AND memory_type='decision' AND memory_id IN ({placeholders})""", params)
                values = [{"mid": r._mapping["memory_id"], "uid": uid, "content": r._mapping["content"],
                           "imp": r._mapping["importance"], "type": r._mapping["memory_type"], "scope": r._mapping["scope"],
                           "scope_cid": r._mapping["scope_conversation_id"]} for r in rows]
                alive = {str(v["mid"]) for v in values}
                if not await memory_service.sync_changes(values, [mid for mid in ids if str(mid) not in alive]):
                    raise ConnectionError("memory index unavailable")
            async with self.jobs.db.transaction():
                await self.jobs.assert_lease(job)
                if rid := job["payload"].get("run_id"):
                    await self.jobs.db.execute("UPDATE user_memory_change SET index_synced=1 WHERE run_id=:rid AND user_id=:uid", {"rid": rid, "uid": uid})
                await self.jobs.complete(job)
        else:
            raise ValueError("unknown background job kind")

    async def run_once(self):
        job = await self.jobs.claim()
        if not job:
            return False
        try:
            await asyncio.wait_for(self.handle(job), 90)
            await self.jobs.complete(job)
        except asyncio.CancelledError:
            # A process crash/shutdown leaves its durable lease for recovery.
            raise
        except Exception as exc:
            await self.jobs.retry(job, exc)
            log.warning("后台任务失败: kind=%s attempt=%s error=%s", job["kind"], job["attempts"], type(exc).__name__)
        return True

    async def loop(self):
        while not self.stop_event.is_set():
            try:
                worked = await self.run_once()
                from app.services.operations import operations
                await operations.cleanup()
                from app.services.index_reconciliation import index_reconciliation
                if not worked:
                    await index_reconciliation.tick()
            except Exception as exc:
                log.warning("后台任务领取失败: %s", type(exc).__name__)
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self.stop_event.wait(), 2)
                except TimeoutError:
                    pass

    def start(self):
        self.stop_event.clear()
        self.task = asyncio.create_task(self.loop())

    async def shutdown(self):
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


durable_jobs = DurableJobs()
background_worker = BackgroundWorker(durable_jobs)
