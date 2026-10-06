"""Check the retired event policy against local MySQL and the running Java API.

Uses an isolated disposable owner. Does not call an LLM or paid embeddings.
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.services.memory import MemoryService
from app.services.durable_jobs import DurableJobs
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    if db.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('Local database only')
    ids = SnowflakeGenerator(worker_id=29)
    uid, cid, decision, event1, event2 = [ids.next_id() for _ in range(5)]
    marker = f'explicit-memory-{uuid4().hex}@sample.invalid'
    report = {'checks': [], 'cleanup_complete': False,
              'scope': 'real local MySQL and Java API; simulated stale ES candidates; no LLM calls'}
    output = ROOT / 'logs/evaluation' / f'explicit-memory-storage-{datetime.now():%Y%m%d-%H%M%S}.json'

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        print(json.dumps(report['checks'][-1], ensure_ascii=False), flush=True)
        if not passed:
            raise AssertionError(name)

    await db.connect()
    try:
        await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,
            join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,'记忆策略验证',:marker,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)""",
            {'uid': uid, 'marker': marker})
        await db.execute("""INSERT INTO ai_conversation(conversation_id,user_id,message_count,total_tokens,status,create_time,update_time)
            VALUES(:cid,:uid,0,0,1,NOW(),NOW())""", {'cid': cid, 'uid': uid})
        for mid, kind in ((decision, 'decision'), (event1, 'event'), (event2, 'event')):
            await db.execute("""INSERT INTO user_memory(memory_id,user_id,content,importance,source_conversation_id,
                create_time,update_time,memory_type,scope,status,memory_key,source_quote)
                VALUES(:mid,:uid,:content,.8,:cid,NOW(),NOW(),:kind,'user','active',:key,:content)""",
                {'mid': mid, 'uid': uid, 'cid': cid, 'kind': kind, 'key': str(mid),
                 'content': '我们确认采用 RRF 融合' if kind == 'decision' else '普通聊天曾经询问 RRF'})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080', trust_env=False,
                headers={'Authorization': 'Bearer ' + local_token(uid)}, timeout=20) as client:
            normal = await client.get('/api/agent/memory', params={'limit': 1})
            normal.raise_for_status()
            data = normal.json()['data']
            check('default_list_excludes_archived_events_before_pagination',
                  [r['memory_id'] for r in data['memories']] == [str(decision)] and data['next_cursor'] is None)
            check('policy_metadata_disables_extraction', data['extraction'] == {'enabled': False})
            archive = (await client.get('/api/agent/memory', params={'kind': 'event', 'limit': 1})).json()['data']
            check('archive_list_has_separate_cursor_and_no_recall',
                  len(archive['memories']) == 1 and archive['next_cursor'] is not None
                  and not archive['memories'][0]['recall_enabled'])
            page2 = (await client.get('/api/agent/memory', params={
                'kind': 'event', 'limit': 1, 'before': archive['next_cursor']})).json()['data']
            check('archive_pagination_has_no_duplicates', len(page2['memories']) == 1
                  and page2['memories'][0]['memory_id'] != archive['memories'][0]['memory_id'])
            old = archive['memories'][0]
            edit = await client.put('/api/agent/memory/records/' + old['memory_id'], json={
                'version': old['version'], 'content': '重新启用旧事件', 'active': True})
            check('archive_reenable_is_rejected_by_backend', edit.status_code == 409)
            service = MemoryService()
            # A stale or defective index returns an old event and a valid decision.
            # The real SQL query must still exclude the event.
            candidates = [{'memory_id': event1, 'score': 1}, {'memory_id': decision, 'score': .9}]
            with patch.object(service, '_search_memories', AsyncMock(return_value=candidates)):
                recalled = await service.recall_details(uid, 'RRF', include_profile=False, conversation_id=cid)
            check('mysql_recheck_excludes_stale_event_candidates',
                  [r['memory_id'] for r in recalled['memories']] == [decision])
            removed = await client.delete('/api/agent/memory/records/' + old['memory_id'],
                params={'version': old['version']})
            removed.raise_for_status()
            stored = await db.fetch_one('SELECT content,status FROM user_memory WHERE memory_id=:mid AND user_id=:uid',
                {'mid': int(old['memory_id']), 'uid': uid})
            check('archived_event_can_be_deleted', stored['status'] == 'deleted' and not stored['content'])
        await DurableJobs().enqueue_extraction(uid, cid, decision)
        check('retired_enqueue_creates_no_background_job', not await db.fetch_val(
            "SELECT COUNT(*) FROM agent_background_job WHERE user_id=:uid AND kind='memory_extract'", {'uid': uid}))
    finally:
        # Never delete an existing user's data: both ID and unique fixture marker must match.
        if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND email=:marker',
                {'uid': uid, 'marker': marker}) == 1:
            async with db.transaction():
                for table in ('agent_background_job', 'user_memory', 'user_profile', 'ai_conversation'):
                    await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:marker', {'uid': uid, 'marker': marker})
            report['cleanup_complete'] = True
        await db.disconnect()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(str(output), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
