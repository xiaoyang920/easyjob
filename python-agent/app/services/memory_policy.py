"""Structured startup context and transactional user-authorized memory mutations."""
import json
import asyncio

from fastapi import HTTPException

from app.clients.mysql_client import db
from app.models.memory_change import validate_memory_changes
from app.models.user_profile import normalize_profile
from app.models.memory_identity import MemoryConflict, canonical_key, canonical_value, key_aliases
from app.services.run_repository import digest
from app.utils.snowflake import snowflake


def decode(value, default):
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value) if value else default


def profile_view(row):
    if not row:
        return {}
    # Read authoritative fields, never an old summary containing cancelled preferences.
    return normalize_profile(dict(row._mapping))


def constraint_view(row):
    r = dict(row._mapping)
    return {"id": str(r["memory_id"]), "type": "constraint", "key": canonical_key('constraint', r["memory_key"]),
            "content": r["content"], "scope": r["scope"],
            "conversation_id": str(r["scope_conversation_id"]) if r.get("scope_conversation_id") else None}


class MemoryPolicyService:
    def __init__(self, database=db):
        self.db = database

    async def enqueue_changes(self, state, changes):
        """Accept once while the executor is authorized; never await ES or write memory here."""
        from app.services.durable_jobs import DurableJobs
        validate_memory_changes(state, changes)
        payload_hash = digest([c.model_dump() for c in changes])
        snapshot = {key: state.get(key) for key in ('user_message', 'memory_source_message',
                    'user_profile', 'active_constraints')}
        snapshot['task_results'] = {tid: {key: result.get(key) for key in
            ('status', 'retrieval_target', 'memory_sources')} for tid, result in (state.get('task_results') or {}).items()
            if result.get('status') == 'succeeded' and result.get('retrieval_target') == 'memory'}
        payload = {'run_id': state['run_id'], 'change_hash': payload_hash,
                   'changes': [c.model_dump() for c in changes], 'snapshot': snapshot}
        async with self.db.transaction():
            run = await self.db.fetch_one("""SELECT run_id FROM agent_run WHERE run_id=:rid AND user_id=:uid
                AND conversation_id=:cid AND execution_token=:token AND status='running'
                AND deadline>UTC_TIMESTAMP(6) AND (executor_lease_until IS NULL OR executor_lease_until>UTC_TIMESTAMP(6))
                FOR UPDATE""", {'rid': state['run_id'], 'uid': state['user_id'],
                    'cid': state['conversation_id'], 'token': state['execution_token']})
            if not run: raise HTTPException(409, '记忆变更的运行已取消或执行代次已失效')
            jid = await DurableJobs(self.db).enqueue(f"memory-write:{state['run_id']}", 'memory_write',
                state['user_id'], state['conversation_id'], payload)
            row = await self.db.fetch_one('SELECT payload FROM agent_background_job WHERE job_id=:id', {'id': jid})
            saved = decode(row._mapping['payload'], {})
            if saved.get('change_hash') != payload_hash:
                raise ValueError('重放的记忆变更与已提交内容不一致')
        return {'memory_changes_queued': True, 'pending_memory_changes': payload['changes'],
                'memory_write_job_id': jid, 'memory_write_status': 'pending'}

    async def finish_write(self, job, status):
        from app.services.durable_jobs import DurableJobs
        async with self.db.transaction():
            await DurableJobs(self.db).assert_lease(job)
            await self.db.execute("""UPDATE agent_background_job SET
                payload=JSON_SET(payload,'$.outcome',:outcome),status='completed',lease_until=NULL,last_error=NULL,updated_at=UTC_TIMESTAMP(6)
                WHERE job_id=:id AND status='running' AND lease_token=:token""",
                {'id': job['job_id'], 'token': job['lease_token'], 'outcome': status})

    async def process_write(self, job):
        from app.models.memory_change import MemoryChange
        payload = job['payload']
        changes = [MemoryChange.model_validate(c) for c in payload['changes']]
        if digest([c.model_dump() for c in changes]) != payload['change_hash']:
            raise ValueError('后台记忆变更内容校验失败')
        state = {**payload['snapshot'], 'run_id': payload['run_id'],
                 'user_id': job['user_id'], 'conversation_id': job['conversation_id']}
        try:
            await self._commit_changes(state, changes, job=job)
        except MemoryConflict:
            await self.finish_write(job, 'conflict')

    async def load_context(self, uid, cid, *, locking=False):
        suffix = " FOR UPDATE" if locking else ""
        profile = profile_view(await self.db.fetch_one("SELECT * FROM user_profile WHERE user_id=:uid" + suffix, {"uid": uid}))
        rows = await self.db.fetch_all("""SELECT memory_id,memory_key,content,scope,scope_conversation_id
            FROM user_memory WHERE user_id=:uid AND memory_type='constraint' AND status='active'
            AND (scope='user' OR (scope='conversation' AND scope_conversation_id=:cid))
            ORDER BY memory_id LIMIT 33""" + suffix, {"uid": uid, "cid": cid})
        if len(rows) > 32 or len(json.dumps(profile, ensure_ascii=False)) > 4000:
            raise ValueError("有效记忆超出启动上下文预算，请整理画像或约束")
        return {"user_profile": profile, "active_constraints": [constraint_view(r) for r in rows]}

    async def apply_changes(self, state, changes):
        result = await self._commit_changes(state, changes)
        # All remote indexing runs after transaction commit, including checkpoint replays.
        await self.sync_index(state["run_id"], state["user_id"], result.pop("_indexed"), result.pop("_removed"))
        return result

    async def _commit_changes(self, state, changes, *, job=None):
        validate_memory_changes(state, changes)
        uid, cid, rid = state["user_id"], state["conversation_id"], state["run_id"]
        payload_hash = digest([c.model_dump() for c in changes])
        indexed, removed = [], []
        async with self.db.transaction():
            # Same row lock as cancellation/settlement: stale executors cannot mutate memory.
            if job:
                from app.services.durable_jobs import DurableJobs
                # Same lock order as run cancellation: conversation -> run -> job -> profile.
                conversation = await self.db.fetch_one('SELECT status FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid FOR UPDATE',
                    {'uid': uid, 'cid': cid})
                run = await self.db.fetch_one('SELECT status FROM agent_run WHERE run_id=:rid AND user_id=:uid AND conversation_id=:cid FOR UPDATE',
                    {'rid': rid, 'uid': uid, 'cid': cid})
                await DurableJobs(self.db).assert_lease(job)
                if not conversation or conversation._mapping['status'] != 1 or not run or run._mapping['status'] in ('cancelled', 'expired'):
                    await self.finish_write(job, 'cancelled')
                    return {}
            else:
                run = await self.db.fetch_one("""SELECT run_id FROM agent_run WHERE run_id=:rid AND user_id=:uid
                    AND conversation_id=:cid AND execution_token=:token AND status='running'
                    AND deadline>UTC_TIMESTAMP(6) FOR UPDATE""",
                    {"rid": rid, "uid": uid, "cid": cid, "token": state["execution_token"]})
                if not run:
                    raise HTTPException(409, "记忆变更的运行已取消或执行代次已失效")
            receipt = await self.db.fetch_one("SELECT * FROM user_memory_change WHERE run_id=:rid", {"rid": rid})
            if receipt:
                r = receipt._mapping
                if r["change_hash"] != payload_hash or r["user_id"] != uid or r["conversation_id"] != cid:
                    raise ValueError("重放的记忆变更与已提交内容不一致")
                result = decode(r["result_json"], {})
                # Persisted changes are already authoritative. Retry their candidate index below.
                indexed = result.get("index_changes", {}).get("upserts", [])
                removed = result.get("index_changes", {}).get("deletes", [])
                context = await self.load_context(uid, cid, locking=True)
                if job: await self.finish_write(job, 'succeeded')
                return {**context, "memory_changes_applied": True, "memory_change_log": result["log"],
                        "_indexed": indexed, "_removed": removed}
            # A shared user-row lock serializes concurrent conversations without replacing whole profiles.
            await self.db.execute("""INSERT INTO user_profile (user_id,tech_stack,interests,experience,preferences,create_time,update_time)
                VALUES (:uid,'[]','[]','unknown','{}',NOW(),NOW()) ON DUPLICATE KEY UPDATE user_id=user_id""", {"uid": uid})
            profile = profile_view(await self.db.fetch_one("SELECT * FROM user_profile WHERE user_id=:uid FOR UPDATE", {"uid": uid}))
            log = []
            for change in changes:
                if change.kind == "profile":
                    before = normalize_profile(state.get("user_profile") or {})
                    if change.key.startswith("preferences."):
                        key = change.key.removeprefix("preferences.")
                        values, expected = profile["preferences"], before.get("preferences", {})
                    else:
                        key, values, expected = change.key, profile, before
                    default = ([] if key == "topics" else "unknown") if values is profile else None
                    target = default if change.operation == 'remove' else change.value
                    if values.get(key, default) == target:
                        log.append({'kind': 'profile', 'operation': 'unchanged', 'key': change.key, 'scope': 'user'})
                        continue
                    if values.get(key, default) != expected.get(key, default):
                        raise MemoryConflict("画像已被另一会话更新，本次未覆盖原值。请重新读取画像后确认修改。")
                    if change.operation == "remove":
                        if values is profile:
                            values[key] = [] if key == "topics" else "unknown"
                        else:
                            values.pop(key, None)
                    else:
                        values[key] = change.value
                else:
                    params = {"uid": uid, "cid": cid, "type": change.kind, "scope": change.scope,
                              "key": canonical_key(change.kind, change.key)}
                    if change.kind == 'constraint':
                        aliases = key_aliases(change.kind, change.key)
                        alias_params = {**{k: v for k, v in params.items() if k != 'key'},
                                        **{f'key{i}': key for i, key in enumerate(aliases)}}
                        placeholders = ','.join(f':key{i}' for i in range(len(aliases)))
                        matches = await self.db.fetch_all(f"""SELECT memory_id,content FROM user_memory WHERE user_id=:uid
                            AND memory_type=:type AND scope=:scope AND memory_key IN ({placeholders}) AND status='active'
                            AND (scope='user' OR scope_conversation_id=:cid) ORDER BY memory_id LIMIT 2 FOR UPDATE""", alias_params)
                        if len(matches) > 1:
                            raise MemoryConflict('这个范围已有多条同类约束，请先在记忆管理页确认并整理要保留的一条。原有记忆尚未改变。')
                        old = matches[0] if matches else None
                    else:
                        old = await self.db.fetch_one("""SELECT memory_id,content FROM user_memory WHERE user_id=:uid
                        AND memory_type=:type AND scope=:scope AND memory_key=:key AND status='active'
                        AND (scope='user' OR scope_conversation_id=:cid) FOR UPDATE""", params)
                    if old and change.operation == 'set' and canonical_value(change.kind, change.key, old._mapping['content']) == change.value:
                        log.append({'kind': change.kind, 'operation': 'unchanged', 'key': params['key'],
                                    'scope': change.scope, 'record_id': str(old._mapping['memory_id'])})
                        continue
                    if (str(old._mapping["memory_id"]) if old else None) != change.record_id:
                        raise MemoryConflict('这个范围已有不同的同类记忆。请确认是否替换原要求，或仅在本次任务中使用新要求；原有记忆尚未改变。')
                    if change.kind == 'decision' and change.operation == 'set' and not old:
                        duplicate = await self.db.fetch_one("""SELECT memory_id FROM user_memory WHERE user_id=:uid
                            AND memory_type='decision' AND scope=:scope AND status='active' AND CAST(content AS BINARY)=CAST(:content AS BINARY)
                            AND (scope='user' OR scope_conversation_id=:cid) ORDER BY memory_id LIMIT 1 FOR UPDATE""",
                            {'uid': uid, 'scope': change.scope, 'cid': cid, 'content': change.value})
                        if duplicate:
                            log.append({'kind': 'decision', 'operation': 'unchanged', 'key': params['key'],
                                        'scope': change.scope, 'record_id': str(duplicate._mapping['memory_id'])})
                            continue
                    if old:
                        mid = old._mapping["memory_id"]
                        await self.db.execute("UPDATE user_memory SET status='inactive',update_time=NOW() WHERE user_id=:uid AND memory_id=:mid",
                                              {"uid": uid, "mid": mid})
                        removed.append(mid)
                    if change.operation == "set":
                        mid = snowflake.next_id()
                        await self.db.execute("""INSERT INTO user_memory (memory_id,user_id,content,importance,
                            source_conversation_id,create_time,update_time,memory_type,scope,scope_conversation_id,status,memory_key,source_quote)
                            VALUES (:mid,:uid,:content,0.8,:cid,NOW(),NOW(),:type,:scope,:scope_cid,'active',:key,:quote)""",
                            {**params, "mid": mid, "content": change.value, "scope_cid": cid if change.scope == "conversation" else None,
                             "quote": change.source_quote})
                        if change.kind == "decision":
                            indexed.append({"mid": mid, "uid": uid, "content": change.value, "imp": 0.8,
                                            "type": "decision", "scope": change.scope,
                                            "scope_cid": cid if change.scope == "conversation" else None})
                log.append({"kind": change.kind, "operation": change.operation, "key": change.key,
                            "scope": change.scope, "removed_id": change.record_id})
            await self.db.execute("""UPDATE user_profile SET tech_stack=:ts,interests=:it,experience=:exp,
                preferences=:pref,summary='',update_time=NOW() WHERE user_id=:uid""",
                {"uid": uid, "ts": '[]',
                 "it": json.dumps(profile["topics"], ensure_ascii=False), "exp": profile["experience"],
                 "pref": json.dumps(profile["preferences"], ensure_ascii=False)})
            context = await self.load_context(uid, cid, locking=True)
            await self.db.execute("""INSERT INTO user_memory_change (run_id,user_id,conversation_id,change_hash,result_json)
                VALUES (:rid,:uid,:cid,:hash,:result)""", {"rid": rid, "uid": uid, "cid": cid, "hash": payload_hash,
                "result": json.dumps({"log": log, "index_changes": {"upserts": indexed, "deletes": removed}}, ensure_ascii=False)})
            from app.services.durable_jobs import DurableJobs
            await DurableJobs(self.db).enqueue(f'memory-change:{rid}', 'memory_index', uid, cid,
                {'ids': [item['mid'] for item in indexed] + removed, 'run_id': rid})
            if job: await self.finish_write(job, 'succeeded')
        # Index is a candidate cache. Inactive MySQL records are excluded even if this fails.
        return {**context, "memory_changes_applied": True, "memory_change_log": log,
                "_indexed": indexed, "_removed": removed}

    async def sync_index(self, rid, uid, indexed, removed):
        from app.services.memory import memory_service
        if indexed:
            params = {"uid": uid, **{f"id{i}": item["mid"] for i, item in enumerate(indexed)}}
            placeholders = ",".join(f":id{i}" for i in range(len(indexed)))
            rows = await self.db.fetch_all(f"SELECT memory_id FROM user_memory WHERE user_id=:uid AND status='active' AND memory_id IN ({placeholders})", params)
            alive = {str(r._mapping["memory_id"]) for r in rows}
            removed = [*removed, *(item["mid"] for item in indexed if str(item["mid"]) not in alive)]
            indexed = [item for item in indexed if str(item["mid"]) in alive]
        try:
            synced = await asyncio.wait_for(memory_service.sync_changes(indexed, removed), 15)
        except TimeoutError:
            synced = False
        if synced:
            await self.db.execute("UPDATE user_memory_change SET index_synced=1 WHERE run_id=:rid AND user_id=:uid", {"rid": rid, "uid": uid})
        return bool(synced)

    async def flush_pending_index(self, uid):
        """Retry durable index operations only on explicit history retrieval, not startup."""
        rows = await self.db.fetch_all("""SELECT run_id,result_json FROM user_memory_change
            WHERE user_id=:uid AND index_synced=0 ORDER BY created_at LIMIT 9""", {"uid": uid})
        for row in rows[:8]:
            job = decode(row._mapping["result_json"], {})["index_changes"]
            if not await self.sync_index(row._mapping["run_id"], uid, job["upserts"], job["deletes"]):
                raise ConnectionError("记忆索引同步暂时不可用")
        if len(rows) > 8:
            raise ConnectionError("记忆索引尚有积压，需要重试同步")


memory_policy_service = MemoryPolicyService()
