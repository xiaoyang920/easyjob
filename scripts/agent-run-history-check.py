"""Real local failed-turn history and source-validity checks; no model calls."""
import asyncio
import hashlib
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
from app.services.run_history import RunHistory
from app.services.stream_delivery import StreamDelivery
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}, 'local fixtures only'
    ids = SnowflakeGenerator(worker_id=29)
    uid, other, aid = [ids.next_id() for _ in range(3)]
    marker = 'run-history-' + uuid4().hex[:10]
    cid = None
    created = []
    runs = []
    report = {'checks': [], 'cleanup_complete': False, 'scope': 'isolated local HTTP/MySQL/Redis; no model calls'}
    conv, repo, history, delivery = ConversationService(), RunRepository(), RunHistory(), StreamDelivery()

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        print(json.dumps(report['checks'][-1]), flush=True)
        assert passed, name

    await db.connect()
    try:
        for who in [uid, other]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,
                join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:id,:name,:email,'LocalRunQa2026!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''',
                {'id': who, 'name': 'RunQA' + str(who)[-8:], 'email': f'{marker}-{who}@sample.invalid', 'marker': marker})
            created.append(who)
        body = '<p>Only current public evidence is reusable.</p>'
        await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,status,deleted,
            required_level,create_time,update_time) VALUES(:aid,:uid,:title,'fixture',:body,1,1,0,0,NOW(),NOW())''',
            {'aid': aid, 'uid': uid, 'title': marker, 'body': body})
        cid = await conv.create_conversation(uid)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', trust_env=False, timeout=20,
                                     headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
            for number in [1, 2]:
                run, _ = await repo.create(cid, uid, str(uuid4()), digest({'fixture': marker, 'n': number}))
                rid, token = run['run_id'], run['execution_token']
                runs.append(rid)
                mid = await conv.add_message(cid, 'user', f'{marker} 请求{number}')
                await repo.record_input(rid, token, mid)
                citation = {'id': 'search_1:1', 'articleId': str(aid), 'sourceHash': hashlib.sha256(body.encode()).hexdigest()}
                artifact = {'task_id': 'search_1', 'kind': 'search', 'actor': 'main', 'status': 'succeeded',
                            'retrieval_target': 'knowledge', 'result': 'Verified fixture result',
                            'instruction': '检索资料', 'citations': [citation], 'article_cards': []}
                await repo.record_progress(rid, token, {'node': 'main_agent', 'tasks': {'search_1': 'succeeded'},
                                                        'results': {'search_1': artifact}})
                await repo.event(rid, 'round_1.main_retrieve', 'succeeded', 100)
                await repo.event(rid, 'round_2.main_agent', 'failed', 200)
                for event in [{'id': 'search', 'label': '检索资料', 'status': 'done'},
                              {'id': 'main', 'label': '根据结果决定下一步', 'status': 'error'}]:
                    await delivery.append(rid, token, 'data:__AGENT_EVENT__:' + json.dumps({
                        'version': 1, 'kind': 'activity', **event}, ensure_ascii=False) + '\n\n')
                await repo.fail(rid, token)
            response = await client.get(f'/agent/conversations/{cid}/messages')
            messages = response.json()['data']
            failed = [m for m in messages if m.get('runStatus') == 'failed']
            check('refresh_returns_both_failed_turns_in_original_order', [m['runId'] for m in failed] == runs
                  and [m['role'] for m in messages] == ['user', 'assistant', 'user', 'assistant'])
            check('completed_activity_and_failure_are_restored', [e['status'] for e in failed[-1]['agentEvents']] == ['done', 'error'])
            again = (await client.get(f'/agent/conversations/{cid}/messages')).json()['data']
            check('repeated_refresh_is_idempotent', again == messages)
            summary, reusable = await history.previous(cid, uid, 'not-a-real-run')
            check('following_turn_receives_failure_position_and_complete_result', summary['node'] == 'main_agent'
                  and next(iter(reusable.values()))['result'] == 'Verified fixture result')
            check('cross_user_context_has_no_results', await history.previous(cid, other, 'current') == ({}, {}))
            forbidden = await client.get(f'/agent/conversations/{cid}/messages', headers={'Authorization': 'Bearer ' + local_token(other)})
            check('cross_user_history_is_denied', forbidden.status_code == 404 or forbidden.json().get('code') == 404)
            await db.execute('UPDATE article_info SET content=:body WHERE article_id=:id AND user_id=:uid',
                             {'id': aid, 'uid': uid, 'body': '<p>Changed evidence.</p>'})
            summary, reusable = await history.previous(cid, uid, 'current')
            check('changed_source_cannot_be_reused', not reusable and summary['unavailable_tasks'] == ['search_1'])
            await db.execute('DELETE FROM agent_stream_frame WHERE run_id=:rid', {'rid': runs[0]})
            fallback = (await client.get(f'/agent/conversations/{cid}/messages')).json()['data']
            check('expired_stream_frames_fall_back_to_durable_node_events', len(fallback[1]['agentEvents']) == 2
                  and fallback[1]['agentEvents'][-1]['status'] == 'error')
            await conv.add_message(cid, 'user', marker + ' 新问题')
            await conv.add_message(cid, 'assistant', '后续成功回答')
            final = (await client.get(f'/agent/conversations/{cid}/messages')).json()['data']
            check('older_failures_remain_after_later_messages', len([m for m in final if m.get('runStatus') == 'failed']) == 2
                  and final[-1]['content'] == '后续成功回答')
            raw = json.dumps(final, ensure_ascii=False)
            check('history_does_not_expose_execution_tokens_or_private_results', 'execution_token' not in raw
                  and 'Verified fixture result' not in raw and 'sourceHash' not in raw)
            status = (await client.get(f'/agent/conversations/{cid}/run')).json()['data']
            check('run_status_keeps_recovery_artifacts_server_side', 'progress' not in (status.get('result') or {})
                  and 'user_message_id' not in (status.get('result') or {}))
    finally:
        for who in created:
            if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:id AND person_introduction=:marker',
                                  {'id': who, 'marker': marker}) != 1:
                raise RuntimeError('fixture ownership changed')
        for rid in runs:
            for table in ['agent_stream_frame', 'agent_run_event', 'agent_task_artifact']:
                await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid': rid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid', {'rid': rid, 'uid': uid})
        if cid:
            await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid': cid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
            await conv.invalidate_cache(cid)
        await db.execute('DELETE FROM article_info WHERE article_id=:id AND user_id=:uid AND title=:marker',
                         {'id': aid, 'uid': uid, 'marker': marker})
        for who in created:
            await db.execute('DELETE FROM user_info WHERE user_id=:id AND person_introduction=:marker', {'id': who, 'marker': marker})
        await conv._redis.client.aclose()
        await db.disconnect()
        report['cleanup_complete'] = True
        output = ROOT / 'logs/evaluation' / f'agent-run-history-{datetime.now():%Y%m%d-%H%M%S}.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(output, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
