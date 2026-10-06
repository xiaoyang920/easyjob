"""Memory controls integration against a dedicated e2e fixture, never a real account."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
import httpx
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.utils.snowflake import snowflake
from evaluation.local_samples import local_token


async def main():
    fixture = json.loads((ROOT / 'logs/evaluation/e2e-20261003-v2/fixture.json').read_text(encoding='utf-8'))
    uid = fixture['uid']
    await db.connect()
    service = ConversationService()
    checks = []
    try:
        owner = await db.fetch_one('SELECT email,person_introduction FROM user_info WHERE user_id=:uid', {'uid': uid})
        assert owner and owner['email'] == fixture['email'] and owner['person_introduction'] == '临时端到端评测账号'
        cid = await db.fetch_val("SELECT conversation_id FROM ai_conversation WHERE user_id=:uid AND title='记忆管理测试对话'", {'uid': uid})
        cid = cid or await service.create_conversation(uid)
        await db.execute("UPDATE ai_conversation SET title='记忆管理测试对话' WHERE conversation_id=:cid AND user_id=:uid", {'cid': cid, 'uid': uid})
        for kind, key, content in [('constraint', 'web_search', 'deny'), ('decision', 'rag_fusion', '已确认采用 RRF 融合检索结果'), ('event', 'redis_discussion', '讨论过 Redis 缓存穿透及布隆过滤器')]:
            if await db.fetch_val('SELECT COUNT(*) FROM user_memory WHERE user_id=:uid AND memory_key=:key', {'uid': uid, 'key': key}): continue
            await db.execute("""INSERT INTO user_memory(memory_id,user_id,content,importance,source_conversation_id,
                create_time,update_time,memory_type,scope,scope_conversation_id,status,memory_key,source_quote)
                VALUES(:mid,:uid,:content,.7,:cid,NOW(),NOW(),:type,'conversation',:cid,'active',:key,:quote)""",
                {'mid': snowflake.next_id(), 'uid': uid, 'content': content, 'cid': cid, 'type': kind, 'key': key, 'quote': content if kind != 'event' else None})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', headers={'Authorization': 'Bearer ' + local_token(uid)}, timeout=30) as client:
            async def overview(kind='all'):
                result = await client.get('/agent/memory', params={'kind': kind}); result.raise_for_status()
                body = result.json(); assert body['code'] == 200, body.get('message')
                return body['data']
            data = await overview()
            assert len(data['memories']) == 2
            assert all(isinstance(m['memory_id'], str) for m in data['memories'])
            checks.append('owner_overview_and_string_ids')
            edit = {**data['profile'], 'version': data['profile_version'], 'topics': ['Java', 'Spring Boot', '分布式系统'], 'preferences': {'language': '中文', 'detail': '详细'}}
            response = await client.put('/agent/memory/profile', json=edit); assert response.json()['code'] == 200, response.text
            stale = await client.put('/agent/memory/profile', json={**edit, 'topics': ['stale']})
            assert stale.status_code == 409 or stale.json().get('code') == 409, stale.text
            checks.append('profile_save_and_stale_version_rejection')
            record = next(m for m in data['memories'] if m['memory_type'] == 'constraint')
            response = await client.put('/agent/memory/records/' + record['memory_id'], json={'version': record['version'], 'content': record['content'], 'active': False})
            assert response.json()['code'] == 200
            assert not await db.fetch_val("SELECT COUNT(*) FROM user_memory WHERE user_id=:uid AND memory_type='constraint' AND status='active'", {'uid': uid})
            checks.append('disable_excludes_constraint_from_startup')
            disabled = next(m for m in (await overview())['memories'] if m['memory_id'] == record['memory_id'])
            response = await client.put('/agent/memory/records/' + disabled['memory_id'], json={'version': disabled['version'], 'content': 'deny', 'active': True})
            assert response.json()['code'] == 200
            active = next(m for m in (await overview())['memories'] if m['memory_type'] == 'constraint' and m['status'] == 'active')
            assert active['memory_id'] != record['memory_id']
            checks.append('reenable_with_new_identity')
            event = next(m for m in (await overview('event'))['memories'] if m['memory_type'] == 'event')
            response = await client.delete('/agent/memory/records/' + event['memory_id'], params={'version': event['version']})
            assert response.json()['code'] == 200
            assert not any(m['memory_id'] == event['memory_id'] for m in (await overview())['memories'])
            erased = await db.fetch_one('SELECT content,source_quote,status FROM user_memory WHERE user_id=:uid AND memory_id=:mid', {'uid': uid, 'mid': int(event['memory_id'])})
            assert erased['content'] == '' and erased['source_quote'] is None and erased['status'] == 'deleted'
            checks.append('delete_erases_content_and_prevents_old_event_reextraction')
            # Supply a valid token for a different principal; cannot edit this owner's record.
            foreign = await client.put('/agent/memory/records/' + active['memory_id'], headers={'Authorization': 'Bearer ' + local_token(uid + 1)}, json={'version': active['version'], 'content': 'allow', 'active': True})
            assert foreign.status_code == 404 or foreign.json().get('code') == 404, foreign.text
            checks.append('cross_user_record_isolation')
            no_auth = await client.get('/agent/memory', headers={'Authorization': ''})
            assert no_auth.status_code == 401 or no_auth.json().get('code') == 401
            checks.append('unauthenticated_request_rejected')
        (ROOT / 'logs/memory-management-live.json').write_text(json.dumps({'checks': checks, 'fixture_uid': str(uid)}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Memory controls: {len(checks)} live checks passed', flush=True)
    finally:
        await service._redis.client.aclose()
        await db.disconnect()


if __name__ == '__main__': asyncio.run(main())
