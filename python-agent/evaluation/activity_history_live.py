"""Opt-in local website refresh check using one disposable real-model run."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.clients.mysql_client import db
from app.services.run_history import instant
from evaluation.context_extended_live import resources, identity, login, cleanup, stream
from evaluation.context_http_live import save


async def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    report = {'passed': False, 'checks': {}, 'cleaned': False}
    async with resources() as (saver, client):
        fixture = await identity()
        save(output / 'fixture.json', fixture)  # Exact cleanup identity; never credentials.
        try:
            await login(client, fixture)
            request = str(uuid4())
            frames = await stream(client, '/api/agent/chat/stream', {
                'requestId': request, 'message': '请用一句中文说明水为什么会结冰。无需检索、写文章或保存记忆。'})
            run = await db.fetch_one('''SELECT run_id,conversation_id,status,
                CONVERT_TZ(created_at,@@session.time_zone,'+00:00') AS created_at,updated_at,result_json
                FROM agent_run WHERE user_id=:uid AND request_id=:request''',
                {'uid': fixture['user_id'], 'request': request})
            assert run and run['status'] == 'succeeded', 'Fixture run did not succeed'
            rid, cid = run['run_id'], run['conversation_id']
            expected = [json.loads(frame[len('__AGENT_EVENT__:'):]) for frame in frames if frame.startswith('__AGENT_EVENT__:')]
            expected_payloads = [{k: v for k, v in event.items() if k != 'timestamp'} for event in expected]
            assert any(event.get('kind') == 'activity' for event in expected)
            before_count = await db.fetch_val('SELECT COUNT(*) FROM agent_run WHERE user_id=:uid', {'uid': fixture['user_id']})
            histories = []
            for _ in range(3):
                response = await client.get(f'/api/agent/conversations/{cid}/messages', params={'limit': 20})
                response.raise_for_status()
                body = response.json()
                assert body['code'] == 200
                items = body['data']['items']
                replies = [item for item in items if item['role'] == 'assistant' and item.get('runId') == rid]
                assert len(replies) == 1, 'Refresh must restore one committed reply'
                histories.append(replies[0])
            first = histories[0]
            restored = first.get('agentEvents') or []
            report['checks'].update({
                'sse_completed': '[DONE]' in frames,
                'successful_reply_hydrated': first.get('runStatus') == 'succeeded',
                'all_stream_activity_payloads_preserved': [{k: v for k, v in event.items() if k != 'timestamp'}
                    for event in restored] == expected_payloads,
                'original_start_time': first.get('runStartedAt') == instant(run['created_at']).isoformat() + 'Z',
                'original_finish_time': first.get('runFinishedAt') == instant(run['updated_at']).isoformat() + 'Z',
                'non_negative_duration': 0 <= (instant(first['runFinishedAt']) - instant(first['runStartedAt'])).total_seconds() < 300,
                'activity_timestamps_within_run': bool(restored) and all(
                    -1 <= (instant(event['timestamp']) - run['created_at']).total_seconds()
                    <= (run['updated_at'] - run['created_at']).total_seconds() + 5 for event in restored),
                'repeated_refresh_is_stable': all(item == first for item in histories),
                'answer_content_unchanged': first['content'] == json.loads(run['result_json'])['reply'],
                'history_does_not_expose_internal_result': not any(key in first for key in ('result_json', 'progress', 'execution_token')),
            })
            # Model calls have already finished. Exercise real retention fallback
            # only on this disposable owner's public stream frames.
            await db.execute('''DELETE f FROM agent_stream_frame f JOIN agent_run r ON r.run_id=f.run_id
                WHERE r.user_id=:uid AND r.run_id=:rid''', {'uid': fixture['user_id'], 'rid': rid})
            response = await client.get(f'/api/agent/conversations/{cid}/messages', params={'limit': 20})
            response.raise_for_status()
            old = next(item for item in response.json()['data']['items'] if item.get('runId') == rid and item['role'] == 'assistant')
            fallback = old.get('agentEvents') or []
            report['checks']['expired_stream_uses_persisted_node_events'] = bool(fallback) and all(event.get('kind') == 'activity' for event in fallback)
            report['checks']['fallback_keeps_original_timing'] = (old['runStartedAt'], old['runFinishedAt']) == (first['runStartedAt'], first['runFinishedAt'])
            report['checks']['fallback_timestamps_within_run'] = bool(fallback) and all(
                -1 <= (instant(event['timestamp']) - run['created_at']).total_seconds()
                <= (run['updated_at'] - run['created_at']).total_seconds() + 5 for event in fallback)
            after_count = await db.fetch_val('SELECT COUNT(*) FROM agent_run WHERE user_id=:uid', {'uid': fixture['user_id']})
            report['checks']['refresh_does_not_execute_a_new_run'] = before_count == after_count == 1
            report.update(activity_count=len({event['id'] for event in restored if event.get('kind') == 'activity'}),
                          fallback_activity_count=len({event['id'] for event in fallback}),
                          elapsed_seconds=(run['updated_at'] - run['created_at']).total_seconds())
            report['passed'] = all(report['checks'].values())
            assert report['passed'], 'Refresh check failed; see report'
        finally:
            save(output / 'report.json', report)
            await cleanup(client, saver, fixture)
            report['cleaned'] = not await db.fetch_val('SELECT user_id FROM user_info WHERE user_id=:uid', {'uid': fixture['user_id']})
            save(output / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(verify(parser.parse_args().output))
