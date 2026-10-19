"""MySQL business ledger and fencing. Checkpoints are isolated by run_id.

All lifecycle mutations lock the conversation before the run. The Java draft
transaction uses the same order to arbitrate cancellation against committing.
"""
import asyncio
import hashlib
import json
import logging
import random
from uuid import uuid4

from fastapi import HTTPException
from pymysql.err import OperationalError

from app.clients.mysql_client import db
from app.config import settings

log = logging.getLogger(__name__)
CREATE_TRANSACTION_ATTEMPTS = 3


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class RunRepository:
    def __init__(self, database=db):
        self.db = database

    async def _lock_conversation(self, cid, uid):
        row = await self.db.fetch_one(
            "SELECT user_id, status FROM ai_conversation WHERE conversation_id=:cid FOR UPDATE", {"cid": cid})
        if not row or row._mapping["status"] != 1 or int(row._mapping["user_id"]) != uid:
            raise HTTPException(404, "会话不存在或无权访问")

    async def get(self, run_id):
        row = await self.db.fetch_one("SELECT * FROM agent_run WHERE run_id=:rid", {"rid": run_id})
        return dict(row._mapping) if row else None

    async def latest(self, cid, uid):
        row = await self.db.fetch_one('''SELECT * FROM agent_run WHERE conversation_id=:cid AND user_id=:uid
            ORDER BY created_at DESC,run_id DESC LIMIT 1''', {'cid': cid, 'uid': uid})
        return dict(row._mapping) if row else None

    async def overview(self, uid):
        rows = await self.db.fetch_all('''SELECT r.run_id,r.conversation_id,r.user_id,r.status,
            r.execution_token,r.draft_article_id,r.deadline,r.executor_lease_until,r.updated_at,c.title FROM agent_run r
            JOIN ai_conversation c ON c.conversation_id=r.conversation_id
            WHERE r.user_id=:uid AND c.user_id=:uid AND c.status=1
            AND NOT EXISTS (SELECT 1 FROM agent_run newer WHERE newer.conversation_id=r.conversation_id
                AND newer.user_id=:uid AND (newer.created_at>r.created_at
                OR (newer.created_at=r.created_at AND newer.run_id>r.run_id)))
            ORDER BY (r.status IN ('running','awaiting_approval')) DESC,r.updated_at DESC LIMIT 100''', {'uid': uid})
        return [dict(row._mapping) for row in rows]

    async def bind_admission(self, run_id, token, ticket):
        # Share the fencing token with the admission lease so recovery can reclaim capacity.
        await self.assert_executor(run_id, token)
        await self.db.execute('UPDATE agent_execution_lease SET ticket=:token WHERE ticket=:ticket',
            {'token': token, 'ticket': ticket})

    async def release_admission(self, run_id):
        await self.db.execute('''DELETE l FROM agent_execution_lease l JOIN agent_run r ON l.ticket=r.execution_token
            WHERE r.run_id=:rid AND r.status IN ('succeeded','awaiting_approval','failed','expired','cancelled')''', {'rid': run_id})

    async def renew_executor(self, run_id, token):
        # A delayed/old process cannot revive an expired lease or extend the run deadline.
        await self.db.execute('''UPDATE agent_run SET executor_lease_until=
            LEAST(deadline,TIMESTAMPADD(SECOND,:lease,UTC_TIMESTAMP(6)))
            WHERE run_id=:rid AND execution_token=:token AND status='running'
            AND deadline>UTC_TIMESTAMP(6) AND executor_lease_until>UTC_TIMESTAMP(6)''',
            {'rid': run_id, 'token': token, 'lease': settings.EXECUTOR_LEASE_SECONDS})
        await self.assert_executor(run_id, token)

    async def pending_approval(self, cid):
        row = await self.db.fetch_one("""SELECT result_json FROM agent_run WHERE conversation_id=:cid
            AND status='awaiting_approval' AND deadline>UTC_TIMESTAMP(6)""", {"cid": cid})
        return json.loads(row._mapping["result_json"])["interrupted"] if row else None

    async def find_request(self, uid, request_id):
        row = await self.db.fetch_one("SELECT * FROM agent_run WHERE user_id=:uid AND request_id=:req",
                                      {"uid": uid, "req": request_id})
        return dict(row._mapping) if row else None

    async def create(self, cid, uid, request_id, input_hash):
        from app.services.service_queries import user_source
        source = await user_source(uid)
        # Retry the whole rolled-back transaction, never the INSERT alone or
        # the graph execution. The request ID and input hash remain unchanged.
        for attempt in range(CREATE_TRANSACTION_ATTEMPTS):
            try:
                return await self._create_once(cid, uid, request_id, input_hash, source)
            except OperationalError as exc:
                if not exc.args or exc.args[0] != 1213 or attempt + 1 == CREATE_TRANSACTION_ATTEMPTS:
                    raise
                log.warning("Run creation deadlock; retrying transaction (%s/%s)",
                            attempt + 2, CREATE_TRANSACTION_ATTEMPTS)
                await asyncio.sleep(0.05 * (2 ** attempt) + random.uniform(0, 0.05))

    async def _create_once(self, cid, uid, request_id, input_hash, source='business'):
        async with self.db.transaction():
            # Take the existing parent row lock before the first consistent
            # read. Same-conversation contenders therefore see their predecessor's
            # commit even under REPEATABLE READ. This method owns its transaction.
            await self._lock_conversation(cid, uid)
            previous = await self.find_request(uid, request_id)
            if previous:
                if previous["input_hash"] != input_hash or previous["conversation_id"] != cid:
                    raise HTTPException(409, "幂等请求与原始输入不一致")
                return previous, False
            # A nonlocking lookup of the unique active slot does not lock an
            # empty index gap. Lifecycle transitions share the parent lock;
            # the unique constraint remains the final concurrency safeguard.
            active = await self.db.fetch_one("""SELECT run_id FROM agent_run
                WHERE active_conversation_id=:cid""", {"cid": cid})
            if active:
                # Lock only an existing primary-key record. Re-read its current
                # status because fail() can terminate an executor independently.
                current = await self.db.fetch_one("""SELECT status, draft_article_id,JSON_EXTRACT(result_json,'$.draft_commit') AS draft_commit,
                    (deadline<=UTC_TIMESTAMP(6) OR (status='running' AND executor_lease_until<=UTC_TIMESTAMP(6))) AS expired FROM agent_run
                    WHERE run_id=:rid FOR UPDATE""", {"rid": active._mapping["run_id"]})
                current_values = dict(current._mapping) if current else {}
                if current and current._mapping["status"] in ("running", "awaiting_approval"):
                    if not current_values["expired"] or current_values["draft_article_id"] is not None or current_values.get('draft_commit'):
                        raise HTTPException(409, "当前会话已有运行或待处理审批")
                    # Expiration fences old executors; a committed draft must
                    # still be reconciled instead of opening a new run.
                    await self.db.execute("""UPDATE agent_run SET status='expired', updated_at=UTC_TIMESTAMP(6)
                        WHERE run_id=:rid""", {"rid": active._mapping["run_id"]})
                    await self.release_admission(active._mapping['run_id'])
            run_id, token = str(uuid4()), str(uuid4())
            await self.db.execute("""INSERT INTO agent_run
                (run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,executor_lease_until,data_source)
                VALUES (:rid,:cid,:uid,:req,:hash,:token,'running',
                        TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)),TIMESTAMPADD(SECOND,:lease,UTC_TIMESTAMP(6)),:source)""",
                {"rid": run_id, "cid": cid, "uid": uid, "req": request_id,
                 "hash": input_hash, "token": token, "ttl": settings.RUN_TIMEOUT_SECONDS, "lease": settings.EXECUTOR_LEASE_SECONDS, "source":source})
            return await self.get(run_id), True

    async def assert_executor(self, run_id, token):
        row = await self.db.fetch_one("""SELECT run_id FROM agent_run WHERE run_id=:rid
            AND execution_token=:token AND status='running'
            AND ((deadline>UTC_TIMESTAMP(6) AND (executor_lease_until IS NULL OR executor_lease_until>UTC_TIMESTAMP(6)))
                 OR draft_article_id IS NOT NULL)""",
            {"rid": run_id, "token": token})
        if not row:
            raise HTTPException(409, "运行已取消、过期或执行代次已改变")

    async def claim_resume(self, cid, uid, run_id, draft_hash):
        async with self.db.transaction():
            await self._lock_conversation(cid, uid)
            row = await self.db.fetch_one("""SELECT * FROM agent_run WHERE run_id=:rid
                AND conversation_id=:cid AND user_id=:uid FOR UPDATE""", {"rid": run_id, "cid": cid, "uid": uid})
            if not row:
                raise HTTPException(409, "审批运行不存在")
            run = dict(row._mapping)
            if run["status"] != "awaiting_approval" or run["draft_hash"] != draft_hash:
                raise HTTPException(409, "审批已失效或草稿版本已改变")
            alive = await self.db.fetch_val("SELECT deadline>UTC_TIMESTAMP(6) FROM agent_run WHERE run_id=:rid",
                                             {"rid": run_id})
            if not alive:
                raise HTTPException(409, "审批已过期")
            token = str(uuid4())
            await self.db.execute("""UPDATE agent_run SET status='running',execution_token=:token,
                deadline=TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)),executor_lease_until=TIMESTAMPADD(SECOND,:lease,UTC_TIMESTAMP(6)),updated_at=UTC_TIMESTAMP(6)
                WHERE run_id=:rid""", {"rid": run_id, "token": token, "ttl": settings.RUN_TIMEOUT_SECONDS, "lease": settings.EXECUTOR_LEASE_SECONDS})
            return await self.get(run_id)

    async def persist_metrics(self, run_id, token, metrics):
        await self.db.execute('''UPDATE agent_run SET result_json=JSON_SET(
            COALESCE(result_json,JSON_OBJECT()),'$.metrics',CAST(:metrics AS JSON))
            WHERE run_id=:rid AND execution_token=:token AND status='running' ''',
            {'rid': run_id, 'token': token, 'metrics': json.dumps(metrics)})

    async def mark_recovery_node(self, run_id, token, node):
        await self.db.execute('''UPDATE agent_run SET result_json=JSON_SET(
            COALESCE(result_json,JSON_OBJECT()),'$.recovery_node',:node)
            WHERE run_id=:rid AND execution_token=:token AND status='running' ''',
            {'rid': run_id, 'token': token, 'node': node})

    async def record_input(self, run_id, token, message_id):
        await self.db.execute('''UPDATE agent_run SET result_json=JSON_SET(
            COALESCE(result_json,JSON_OBJECT()),'$.user_message_id',:mid)
            WHERE run_id=:rid AND execution_token=:token AND status='running' ''',
            {'rid': run_id, 'token': token, 'mid': str(message_id)})

    async def record_progress(self, run_id, token, progress):
        await self.db.execute('''UPDATE agent_run SET result_json=JSON_SET(
            COALESCE(result_json,JSON_OBJECT()),'$.progress',CAST(:progress AS JSON))
            WHERE run_id=:rid AND execution_token=:token AND status='running' ''',
            {'rid': run_id, 'token': token, 'progress': json.dumps(progress, ensure_ascii=False)})

    async def record_delivery_failure(self, run_id, token, audit, notice):
        await self.db.execute('''UPDATE agent_run SET result_json=JSON_SET(
            COALESCE(result_json,JSON_OBJECT()),'$.grounding_audit',CAST(:audit AS JSON),
            '$.failure_notice',:notice)
            WHERE run_id=:rid AND execution_token=:token AND status='running'
            AND draft_article_id IS NULL AND JSON_EXTRACT(result_json,'$.draft_commit') IS NULL''',
            {'rid': run_id, 'token': token, 'audit': json.dumps(audit, ensure_ascii=False), 'notice': notice})

    async def claim_recovery(self, cid, uid, rid):
        async with self.db.transaction():
            await self._lock_conversation(cid, uid)
            row = await self.db.fetch_one('SELECT * FROM agent_run WHERE run_id=:rid FOR UPDATE', {'rid': rid})
            if not row or row._mapping['user_id'] != uid or row._mapping['conversation_id'] != cid:
                raise HTTPException(404, '运行不存在')
            run = dict(row._mapping)
            latest = await self.latest(cid, uid)
            active = await self.db.fetch_val('SELECT run_id FROM agent_run WHERE active_conversation_id=:cid', {'cid': cid})
            if (run['status'] not in ('failed', 'expired') or run.get('draft_article_id')
                    or run.get('recovery_count', 0) >= 1 or active or not latest or latest['run_id'] != rid):
                raise HTTPException(409, '该运行不能恢复，请重新提问')
            token = str(uuid4())
            await self.db.execute('''UPDATE agent_run SET status='running',execution_token=:token,
                recovery_count=recovery_count+1,deadline=TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)),
                executor_lease_until=TIMESTAMPADD(SECOND,:lease,UTC_TIMESTAMP(6)),updated_at=UTC_TIMESTAMP(6)
                WHERE run_id=:rid''', {'rid': rid, 'token': token, 'ttl': settings.RUN_TIMEOUT_SECONDS,
                                     'lease': settings.EXECUTOR_LEASE_SECONDS})
            return await self.get(rid)

    async def settle(self, cid, uid, run_id, token, status, result, append_message=None):
        async with self.db.transaction():
            await self._lock_conversation(cid, uid)
            row = await self.db.fetch_one("SELECT * FROM agent_run WHERE run_id=:rid FOR UPDATE", {"rid": run_id})
            if not row or row._mapping["execution_token"] != token:
                raise HTTPException(409, "执行代次已失效")
            current = dict(row._mapping)
            if current["conversation_id"] != cid or current["user_id"] != uid:
                raise HTTPException(404, "运行不存在或无权访问")
            if current["status"] == "succeeded":
                return json.loads(current["result_json"])
            if current["status"] != "running":
                raise HTTPException(409, "运行已经终止")
            await self.assert_executor(run_id, token)
            if append_message:
                await append_message()
            # Keep the input anchor/progress through approval, recovery and settlement.
            result = {**json.loads(current.get('result_json') or '{}'), **result}
            await self.db.execute("""UPDATE agent_run SET status=:status,result_json=:result,draft_hash=COALESCE(:hash,draft_hash),
                executor_lease_until=NULL,
                deadline=IF(:status='awaiting_approval',TIMESTAMPADD(SECOND,:ttl,UTC_TIMESTAMP(6)),deadline),
                updated_at=UTC_TIMESTAMP(6) WHERE run_id=:rid""",
                {"rid": run_id, "status": status, "result": json.dumps(result, ensure_ascii=False),
                 "hash": (result.get("interrupted") or {}).get("draftHash"),
                 "ttl": settings.APPROVAL_TIMEOUT_SECONDS})
            return result

    async def fail(self, run_id, token):
        # A committed draft is a successful side effect, even if delivery failed.
        # Reconciliation returns it rather than executing generation again.
        await self.db.execute("""UPDATE agent_run SET status='failed',updated_at=UTC_TIMESTAMP(6)
            WHERE run_id=:rid AND execution_token=:token AND status='running' AND draft_article_id IS NULL
            AND JSON_EXTRACT(result_json,'$.draft_commit') IS NULL""",
            {"rid": run_id, "token": token})
        await self.release_admission(run_id)

    async def expire_existing(self, cid, uid, run_id):
        """Maintenance shares the parent/run lock order with approval and saves."""
        async with self.db.transaction():
            await self._lock_conversation(cid, uid)
            row = await self.db.fetch_one("""SELECT status,draft_article_id,
                (deadline<=UTC_TIMESTAMP(6) OR (status='running' AND executor_lease_until<=UTC_TIMESTAMP(6))) AS expired
                FROM agent_run WHERE run_id=:rid AND user_id=:uid AND conversation_id=:cid FOR UPDATE""",
                {'rid': run_id, 'uid': uid, 'cid': cid})
            if not row or row._mapping['status'] not in ('running', 'awaiting_approval') or not row._mapping['expired'] or row._mapping['draft_article_id'] is not None:
                return False
            if await self.db.fetch_val("SELECT JSON_EXTRACT(result_json,'$.draft_commit') FROM agent_run WHERE run_id=:rid", {'rid':run_id}):
                return False
            await self.db.execute("""UPDATE agent_run SET status='expired',updated_at=UTC_TIMESTAMP(6)
                WHERE run_id=:rid""", {'rid': run_id})
            await self.release_admission(run_id)
            return True

    async def cancel(self, cid, uid):
        async with self.db.transaction():
            await self._lock_conversation(cid, uid)
            row = await self.db.fetch_one("""SELECT * FROM agent_run WHERE conversation_id=:cid
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", {"cid": cid})
            if not row:
                return {"status": "idle"}
            run = dict(row._mapping)
            if run["draft_article_id"]:
                return {"status": "draft_saved", "draftArticleId": str(run["draft_article_id"])}
            if json.loads(run.get('result_json') or '{}').get('draft_commit'):
                return {"status": "saving", "message": "草稿正在保存，完成后可在草稿箱查看"}
            if run["status"] in ("running", "awaiting_approval"):
                await self.db.execute("UPDATE agent_run SET status='cancelled',updated_at=UTC_TIMESTAMP(6) WHERE run_id=:rid",
                                      {"rid": run["run_id"]})
                await self.release_admission(run['run_id'])
            return {"status": "cancelled" if run["status"] in ("running", "awaiting_approval") else run["status"],
                    "runId": run["run_id"]}

    async def event(self, run_id, node, status, duration_ms=None):
        await self.db.execute("""INSERT INTO agent_run_event (run_id,node,status,duration_ms)
            VALUES (:rid,:node,:status,:ms)""", {"rid": run_id, "node": node, "status": status, "ms": duration_ms})


run_repository = RunRepository()
