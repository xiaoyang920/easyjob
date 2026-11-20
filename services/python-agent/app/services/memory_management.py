"""Owner-scoped memory controls; MySQL remains authoritative for recall."""
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.clients.mysql_client import db
from app.services.durable_jobs import DurableJobs
from app.services.memory_policy import profile_view
from app.models.memory_identity import canonical_key, canonical_value, key_aliases
from app.models.user_profile import merge_topics
from app.services.run_repository import digest
from app.utils.snowflake import snowflake


class ProfileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    topics: list[str] = Field(default_factory=list, max_length=40)
    experience: str = Field(default="unknown", min_length=1, max_length=100)
    preferences: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounds(self):
        if any(not v.strip() or len(v) > 100 for v in self.topics):
            raise ValueError("关注领域每项需为1～100字，最多40项")
        self.topics = merge_topics(self.topics)
        if len(self.preferences) > 20 or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k)
                or not v.strip() or len(v) > 1000 for k, v in self.preferences.items()):
            raise ValueError("偏好最多20项，使用英文小写字段名和非空短文本")
        if len(json.dumps(self.model_dump(exclude={'version'}), ensure_ascii=False)) > 4000:
            raise ValueError("画像内容超过4000字限制")
        return self


class RecordEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: str = Field(min_length=1, max_length=1000)
    active: bool


def record_view(row):
    value = dict(row._mapping)
    value['recall_enabled'] = value.get('memory_type') in ('constraint', 'decision') and value.get('status') == 'active'
    value['version'] = digest({k: str(value.get(k)) for k in
                              ('memory_id', 'content', 'status', 'update_time')})
    for key in ('memory_id', 'source_conversation_id', 'scope_conversation_id'):
        if value.get(key) is not None:
            value[key] = str(value[key])
    return value


class MemoryManagement:
    def __init__(self, database=db):
        self.db = database

    async def overview(self, uid, *, before=None, limit=30, kind='all'):
        if kind not in ('all', 'constraint', 'decision', 'event'):
            raise HTTPException(422, '记忆类型无效')
        profile_row = await self.db.fetch_one('SELECT * FROM user_profile WHERE user_id=:uid', {'uid': uid})
        profile = profile_view(profile_row) or {'topics': [], 'experience': 'unknown', 'preferences': {}}
        rows = await self.db.fetch_all("""SELECT m.*,c.title AS source_title FROM user_memory m
            LEFT JOIN ai_conversation c ON c.conversation_id=m.source_conversation_id AND c.user_id=m.user_id AND c.status=1
            WHERE m.user_id=:uid AND m.status IN ('active','inactive') AND (:before IS NULL OR m.memory_id<:before)
            AND ((:kind='all' AND m.memory_type IN ('constraint','decision')) OR m.memory_type=:kind)
            ORDER BY m.memory_id DESC LIMIT :limit""", {'uid': uid, 'before': before, 'limit': limit + 1, 'kind': kind})
        writes = await self.db.fetch_all("""SELECT job_id,status,attempts,created_at,updated_at,
            JSON_UNQUOTE(JSON_EXTRACT(payload,'$.outcome')) AS outcome FROM agent_background_job
            WHERE user_id=:uid AND kind='memory_write'
            ORDER BY (status IN ('pending','running')) DESC,created_at DESC LIMIT 10""", {'uid': uid})
        return {'profile': profile, 'profile_version': digest(profile),
                'profile_updated_at': dict(profile_row._mapping).get('update_time') if profile_row else None,
                'memories': [record_view(r) for r in rows[:limit]],
                'next_cursor': str(rows[limit - 1]._mapping['memory_id']) if len(rows) > limit else None,
                'extraction': {'enabled': False}, 'memory_policy': 'explicit_profile_constraint_decision',
                'write_jobs': [{'id': r._mapping['job_id'],
                    'status': r._mapping['outcome'] if r._mapping['status'] == 'completed' else
                              ('failed' if r._mapping['status'] == 'dead' else 'pending'),
                    'updated_at': r._mapping['updated_at'].isoformat() + 'Z'} for r in writes]}

    async def save_profile(self, uid, edit):
        async with self.db.transaction():
            # Same lock as Main's profile/constraint mutations, including a missing row.
            await self.db.execute("""INSERT INTO user_profile(user_id,tech_stack,interests,preferences,experience,create_time,update_time)
                VALUES(:uid,'[]','[]','{}','unknown',NOW(),NOW()) ON DUPLICATE KEY UPDATE user_id=user_id""", {'uid': uid})
            row = await self.db.fetch_one('SELECT * FROM user_profile WHERE user_id=:uid FOR UPDATE', {'uid': uid})
            if digest(profile_view(row)) != edit.version:
                raise HTTPException(409, '画像已更新，请重新加载后编辑')
            await self.db.execute("""UPDATE user_profile SET tech_stack=:ts,interests=:it,experience=:exp,
                preferences=:pref,summary='',update_time=NOW() WHERE user_id=:uid""",
                {'uid': uid, 'ts': '[]',
                 'it': json.dumps(edit.topics, ensure_ascii=False), 'exp': edit.experience,
                 'pref': json.dumps(edit.preferences, ensure_ascii=False)})

    async def change_record(self, uid, mid, version, *, edit=None):
        async with self.db.transaction():
            await self.db.execute("""INSERT INTO user_profile(user_id,tech_stack,interests,preferences,experience,create_time,update_time)
                VALUES(:uid,'[]','[]','{}','unknown',NOW(),NOW()) ON DUPLICATE KEY UPDATE user_id=user_id""", {'uid': uid})
            await self.db.fetch_one('SELECT user_id FROM user_profile WHERE user_id=:uid FOR UPDATE', {'uid': uid})
            row = await self.db.fetch_one('SELECT * FROM user_memory WHERE user_id=:uid AND memory_id=:mid FOR UPDATE', {'uid': uid, 'mid': mid})
            if not row or row._mapping['status'] == 'deleted':
                raise HTTPException(404, '记忆不存在')
            old = dict(row._mapping)
            if record_view(row)['version'] != version:
                raise HTTPException(409, '记忆已更新，请重新加载后编辑')
            if old['memory_type'] == 'event' and edit is not None:
                raise HTTPException(409, '旧历史事件已归档，不支持编辑或重新启用；可以删除')
            ids = [mid]
            if edit is None:
                # Erase text/quote while retaining the deduplication key: a later
                # extraction of the same historical window must not resurrect it.
                await self.db.execute("UPDATE user_memory SET content='',source_quote=NULL,status='deleted',update_time=NOW() WHERE user_id=:uid AND memory_id=:mid", {'uid': uid, 'mid': mid})
            else:
                content = canonical_value(old['memory_type'], old['memory_key'], edit.content.strip())
                if not content or (old['memory_type'] == 'constraint' and old['memory_key'] == 'web_search' and content not in ('allow', 'deny')):
                    raise HTTPException(422, '联网约束仅允许 allow 或 deny，其他记忆不能为空')
                if edit.active and old['memory_type'] == 'constraint':
                    count = await self.db.fetch_val("""SELECT COUNT(*) FROM user_memory WHERE user_id=:uid AND memory_type='constraint'
                        AND status='active' AND memory_id<>:mid""", {'uid': uid, 'mid': mid})
                    if count >= 32:
                        raise HTTPException(422, '有效约束最多32条，请先停用其他约束')
                if edit.active:
                    aliases = key_aliases(old['memory_type'], old['memory_key'])
                    key_params = {f'key{i}': key for i, key in enumerate(aliases)}
                    placeholders = ','.join(f':key{i}' for i in range(len(aliases)))
                    conflict = await self.db.fetch_one(f"""SELECT memory_id FROM user_memory WHERE user_id=:uid
                        AND memory_type=:type AND scope=:scope AND memory_key IN ({placeholders}) AND status='active' AND memory_id<>:mid
                        AND (scope='user' OR scope_conversation_id=:cid) FOR UPDATE""",
                        {'uid': uid, 'mid': mid, 'type': old['memory_type'], 'scope': old['scope'],
                         'cid': old['scope_conversation_id'], **key_params})
                    if conflict:
                        raise HTTPException(409, '同范围已有有效记录，请编辑当前记录')
                    if old['memory_type'] == 'decision':
                        duplicate = await self.db.fetch_one("""SELECT memory_id FROM user_memory WHERE user_id=:uid
                            AND memory_type='decision' AND scope=:scope AND status='active' AND memory_id<>:mid
                            AND CAST(content AS BINARY)=CAST(:content AS BINARY) AND (scope='user' OR scope_conversation_id=:cid) LIMIT 1 FOR UPDATE""",
                            {'uid': uid, 'mid': mid, 'scope': old['scope'], 'cid': old['scope_conversation_id'], 'content': content})
                        if duplicate:
                            raise HTTPException(409, '同范围已有相同决策，不需要重复保存')
                # Replacements get a new identity. An in-flight Main holding the old
                # id cannot accidentally remove a newly edited/reenabled constraint.
                await self.db.execute("UPDATE user_memory SET status=:status,update_time=NOW() WHERE user_id=:uid AND memory_id=:mid",
                    {'uid': uid, 'mid': mid, 'status': 'superseded' if edit.active else 'inactive'})
                if edit.active:
                    new_id = snowflake.next_id()
                    await self.db.execute("""INSERT INTO user_memory(memory_id,user_id,content,importance,source_conversation_id,
                        create_time,update_time,memory_type,scope,scope_conversation_id,status,memory_key,source_quote)
                        VALUES(:id,:uid,:content,:imp,:cid,NOW(),NOW(),:type,:scope,:scope_cid,'active',:key,:quote)""",
                        {'id': new_id, 'uid': uid, 'content': content, 'imp': old['importance'], 'cid': old['source_conversation_id'],
                         'type': old['memory_type'], 'scope': old['scope'], 'scope_cid': old['scope_conversation_id'],
                         'key': canonical_key(old['memory_type'], old['memory_key']), 'quote': old.get('source_quote')})
                    ids.append(new_id)
                elif content != old['content']:
                    await self.db.execute('UPDATE user_memory SET content=:content WHERE user_id=:uid AND memory_id=:mid', {'uid': uid, 'mid': mid, 'content': content})
            # DB mutation and retryable ES maintenance are one transaction. Recall
            # always rechecks MySQL, so delayed ES cleanup cannot revive a memory.
            await DurableJobs(self.db).enqueue('memory-manage:' + str(uuid4()), 'memory_index', uid,
                old['source_conversation_id'], {'ids': ids})


memory_management = MemoryManagement()
