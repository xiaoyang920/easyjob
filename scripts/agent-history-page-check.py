"""Isolated 100-turn MySQL/HTTP pagination checks, without model calls."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.services.run_repository import RunRepository, digest
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}, 'local fixtures only'
    ids = SnowflakeGenerator(worker_id=28)
    uid, other = ids.next_id(), ids.next_id()
    marker = 'history-pages-' + uuid4().hex[:10]
    created, mids, runs = [], [], []
    cid = None
    conv, repo = ConversationService(), RunRepository()
    report = {'turns': 100, 'checks': [], 'cleanup_complete': False, 'scope': 'local MySQL/HTTP, no model calls'}
    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        print(json.dumps(report['checks'][-1]), flush=True)
        assert passed, name
    await db.connect()
    try:
        for who in [uid, other]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,
                join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:id,:name,:email,'LocalQa2026!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''',
                {'id': who, 'name': 'PageQA' + str(who)[-8:], 'email': f'{marker}-{who}@sample.invalid', 'marker': marker})
            created.append(who)
        cid = await conv.create_conversation(uid)
        async with db.transaction():
            for n in range(100):
                mid = ids.next_id(); mids.append(mid)
                for message_id, role, content in [(mid, 'user', f'Question {n+1}'), (ids.next_id(), 'assistant', 'Answer ' + str(n+1) + ' ' + 'body ' * 200)]:
                    await db.execute('''INSERT INTO ai_message(message_id,conversation_id,role,content,token_count,create_time)
                        VALUES(:mid,:cid,:role,:content,10,NOW())''', {'mid': message_id, 'cid': cid, 'role': role, 'content': content})
        run, _ = await repo.create(cid, uid, str(uuid4()), digest({'fixture': marker}))
        runs.append(run['run_id'])
        await repo.record_input(run['run_id'], run['execution_token'], mids[9])
        await repo.event(run['run_id'], 'main_agent', 'failed', 1)
        await repo.fail(run['run_id'], run['execution_token'])
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', trust_env=False, timeout=30,
            headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
            async def page(**params):
                response = await client.get(f'/agent/conversations/{cid}/messages', params={'limit': 20, **params})
                assert response.status_code == 200 and response.json()['code'] == 200, response.text[:400]
                return response.json()['data']
            latest = await page()
            check('latest_contains_only_20_complete_turns', len(latest['items']) == 40 and latest['items'][0]['content'] == 'Question 81')
            check('latest_does_not_include_old_failure', not any(m.get('runId') == runs[0] for m in latest['items']))
            older = await page(before=latest['beforeCursor'])
            check('older_keyset_has_no_duplicates_or_orphan_answer', older['items'][0]['content'] == 'Question 61' and len(older['items']) == 40
                and not set(m['itemId'] for m in latest['items']) & set(m['itemId'] for m in older['items']))
            around = await page(around=mids[9])
            check('around_loads_requested_question_and_its_failure', any(m.get('messageId') == str(mids[9]) for m in around['items'])
                  and len([m for m in around['items'] if m.get('runId') == runs[0]]) == 1)
            check('failure_preserves_its_turn_identity', next(m for m in around['items'] if m.get('runId') == runs[0])['turnId'] == str(mids[9]))
            newer = await page(after=older['afterCursor'])
            check('forward_page_matches_latest', newer == latest)
            index, cursor, snapshot = [], None, None
            while True:
                data = (await client.get(f'/agent/conversations/{cid}/questions', params={k:v for k,v in
                    {'limit': 17, 'after': cursor, 'snapshot': snapshot}.items() if v is not None})).json()['data']
                index.extend(data['items']); cursor, snapshot = data['nextCursor'], data['snapshot']
                if not data['hasMore']: break
            check('question_index_paginates_all_100_in_original_order', [q['messageId'] for q in index] == list(map(str, mids)))
            check('question_index_contains_short_previews_only', all(len(q['question']) <= 256 and len(q['answer'] or '') <= 384
                and 'imagePaths' not in q and 'content' not in q for q in index))
            for endpoint in ['messages?limit=20', 'questions']:
                response = await client.get(f'/agent/conversations/{cid}/{endpoint}', headers={'Authorization': 'Bearer ' + local_token(other)})
                check('cross_user_denied_' + endpoint.split('?')[0], response.status_code == 404 or response.json().get('code') == 404)
            for name, params in [('conflicting_cursors', {'before': mids[5], 'after': mids[6]}), ('invalid_limit', {'limit': 51}),
                                 ('unknown_question', {'around': 1})]:
                response = await client.get(f'/agent/conversations/{cid}/messages', params={'limit': 20, **params})
                check(name, response.status_code in [400, 404, 422] or response.json().get('code') in [400, 404, 422])
            check('repeat_page_is_idempotent', await page() == latest)
            await conv.add_message(cid, 'user', 'New appended question')
            data = (await client.get(f'/agent/conversations/{cid}/questions', params={'snapshot': snapshot, 'limit': 200})).json()['data']
            check('index_snapshot_excludes_concurrent_new_turn', len(data['items']) == 100)
    finally:
        for who in created:
            assert await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:id AND person_introduction=:marker', {'id': who, 'marker': marker}) == 1
        for rid in runs:
            for table in ['agent_stream_frame', 'agent_run_event', 'agent_task_artifact']:
                await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid': rid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid', {'rid': rid, 'uid': uid})
        if cid:
            await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid': cid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
            await conv.invalidate_cache(cid)
        for who in created:
            await db.execute('DELETE FROM user_info WHERE user_id=:id AND person_introduction=:marker', {'id': who, 'marker': marker})
        await conv._redis.client.aclose()
        await db.disconnect()
        report['cleanup_complete'] = True
        output = ROOT / 'logs/evaluation' / f'agent-history-pages-{datetime.now():%Y%m%d-%H%M%S}.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(output, flush=True)

if __name__ == '__main__':
    asyncio.run(main())
