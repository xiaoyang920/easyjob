"""Opt-in local website -> gateway -> Java -> Agent -> provider context smoke.

Uses a disposable fixture identity; never reuses a person's conversations.
Run: python -m evaluation.context_http_live --output temp/context-http-unique
"""
import argparse
import asyncio
import json
import secrets
import time
from pathlib import Path
from uuid import uuid4

import httpx
from redis.asyncio import Redis

from app.clients.mysql_client import db
from app.config import settings
from app.services.checkpoint_store import LatestRunRedisSaver
from app.utils.snowflake import SnowflakeGenerator
from evaluation.fixture_cleanup import revoke_sessions


def save(path, report):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def result_recovery_case(client, saver, uid, *, race=False):
    """Seed a synthetic interrupted business checkpoint, then use real HTTP recovery."""
    from app.services.conversation import ConversationService
    from app.services.run_repository import run_repository, digest
    from app.services.run_service import RunService
    from app.services.memory import memory_service
    from app.graph.builder import _build_graph
    from app.graph.state_factory import create_initial_state
    from evaluation.context_live import parse_json
    conversations = ConversationService()
    cid = await conversations.create_conversation(uid)
    message = ('从已有结果log_0中定位现场校验代号。只返回JSON：target_code填代号。'
               '不要联网、重新检索、写文章或修改记忆。')
    mid = await conversations.add_message(cid, 'user', message, postprocess=False)
    run, _ = await run_repository.create(cid, uid, str(uuid4()), digest({'fixture': message}))
    config = RunService.config(run)
    await run_repository.record_input(run['run_id'], run['execution_token'], mid)
    state = create_initial_state(uid, message, [])
    state.update(run_id=run['run_id'], execution_token=run['execution_token'], conversation_id=cid,
                 user_message_id=str(mid), **(await memory_service.load_context(uid, cid)))
    original = 'ordinary log ' * 7000 + '\n现场校验代号：HTTP-RECOVER-K8P2\n' + 'tail ' * 1000
    source = {'status': 'succeeded', 'kind': 'search', 'actor': 'main', 'retrieval_target': 'knowledge',
        'result': original, 'instruction': '已有合成日志', 'citations': [
            {'id': 'log_0:1', 'title': '合成恢复验收日志', 'contentScope': 'fixture_text'}],
        'citation_contents': {'log_0:1': original}, 'article_cards': []}
    state['task_results'] = {'log_0': source}
    graph = _build_graph().compile(checkpointer=saver)
    await graph.aupdate_state(config, state, as_node='main_delegate')
    before = await graph.aget_state(config)
    assert before.next == ('main_agent',), 'Fixture must resume at a real Main node'
    await run_repository.fail(run['run_id'], run['execution_token'])
    started = time.perf_counter()
    async def recover():
        frames, lines = [], []
        async with client.stream('POST', f"/api/agent/runs/{run['run_id']}/recover") as response:
            if race and response.status_code == 409:
                return [], 409
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith('data:'):
                    lines.append(line[5:].removeprefix(' '))
                elif not line and lines:
                    frames.append('\n'.join(lines)); lines = []
        if lines: frames.append('\n'.join(lines))
        return frames, 200
    responses = await asyncio.gather(*(recover() for _ in range(2 if race else 1)))
    frames = next((frames for frames, code in responses if code == 200), [])
    record = await run_repository.get(run['run_id'])
    snapshot = await saver.aget_tuple(config)
    restored = snapshot.checkpoint.get('channel_values', {}) if snapshot else {}
    replies = [json.loads(f.split(':', 1)[1])['content'] for f in frames if f.startswith('__REPLY__:')]
    answer = replies[-1] if replies else restored.get('final_reply', '')
    reads = [r for r in (restored.get('task_results') or {}).values() if r.get('tool_name') in
             ('read_task_result', 'read_task_results')]
    result = json.loads(record['result_json'] or '{}')
    metrics = result.get('metrics') or {}
    prefetched = (restored.get('result_prefetch_metrics') or {}).get('status') == 'hit'
    scoped_reads = [read for scope in (restored.get('answer_source_scope') or {}).values()
                    for read in scope.get('reads') or []]
    checks = {'sse_done': '[DONE]' in frames, 'no_error_frame': not any(f.startswith('[ERROR]') for f in frames),
        'same_run_recovered': record['status'] == 'succeeded' and record.get('recovery_count', 0) > 0,
        'new_execution_generation': record['execution_token'] != run['execution_token'],
        'exact_code': parse_json(answer).get('target_code') == 'HTTP-RECOVER-K8P2',
        'state_local_evidence_loaded': (len(reads) == 1 and reads[0].get('status') == 'succeeded')
            or (not reads and prefetched and bool(scoped_reads)),
        'original_checkpoint_result_unchanged': restored.get('task_results', {}).get('log_0') == source,
        'read_metadata_persisted': bool((reads and reads[0].get('result_reads')) or scoped_reads),
        'provider_usage_recorded': metrics.get('measured_input_tokens', 0) > 0}
    if race:
        checks['one_recovery_generation'] = record['recovery_count'] == 1
        checks['one_assistant_message'] = await db.fetch_val("SELECT COUNT(*) FROM ai_message WHERE conversation_id=:cid AND role='assistant'",
                                                           {'cid': cid}) == 1
    return {'id': 'result_read_after_real_http_recovery', 'run_id': run['run_id'], 'conversation_id': str(cid),
            'synthetic_interrupted_checkpoint': True, 'concurrent_recovery': race,
            'response_statuses': [code for _, code in responses], 'prefetched': prefetched, 'explicit_reads': len(reads), 'reply': answer, 'checks': checks,
            'passed': all(checks.values()), 'metrics': metrics,
            'elapsed_ms': round((time.perf_counter()-started)*1000)}


async def run(output, result_recovery=False):
    assert db.url.hostname in {'127.0.0.1', 'localhost', '::1'}, 'Local database only'
    assert settings.REDIS_STACK_HOST in {'127.0.0.1', 'localhost', '::1'}, 'Local checkpoints only'
    output.mkdir(parents=True, exist_ok=False)
    report_path = output / 'report.json'
    marker = 'context-http-' + uuid4().hex[:10]
    uid = SnowflakeGenerator(worker_id=27).next_id()
    email, password = marker + '@example.invalid', secrets.token_urlsafe(28)
    report = {'entry': 'http://127.0.0.1:3000/api/agent/chat/stream',
              'fixture_user_id': str(uid), 'fixture_email': email, 'cases': [], 'cleanup': False}
    save(report_path, report)
    await db.connect()
    redis = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT,
                  db=settings.REDIS_STACK_DB, password=settings.REDIS_STACK_PASSWORD or None)
    saver = LatestRunRedisSaver(redis_client=redis)
    await saver.__aenter__()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:3000',
                                 timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
        conversation = None
        try:
            await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,
                total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count,data_source)
                VALUES (:uid,:name,:email,:password,NOW(),2,1,0,0,1,1,0,0,0,'evaluation')""",
                {'uid': uid, 'name': 'ctx-' + marker[-10:], 'email': email, 'password': password})
            login = await client.post('/api/auth/login', json={'email': email, 'password': password})
            login.raise_for_status()
            body = login.json()
            assert body['code'] == 200, 'Fixture login failed'
            client.headers['Authorization'] = 'Bearer ' + body['data']['token']
            client.cookies.clear()
            prompts = [
                ('requirements_initial', '这是仅用于当前会话的测试，不要保存长期记忆，也不要搜索或写文章。'
                 '请记住当前任务：项目代号灯塔-N9，用中文，输出格式用表格，截止日期2026-11-10，技术栈Java 17。请简短确认。'),
                ('requirements_revoked', '修改当前任务：取消表格，改成三条列表；取消2026-11-10这个截止日期，改为2026-11-20。其余要求不变。请简短确认。'),
                ('requirements_final', '只输出当前任务要求的JSON，字段为project、language、format、deadline、stack；'
                 'format值写三条列表，language值写中文，不要附加说明。'),
            ]
            prompts.extend((f'requirements_final_repeat_{i}', prompts[-1][1]) for i in range(1, 3))
            for case_id, message in prompts:
                request_id = str(uuid4())
                payload = {'requestId': request_id, 'message': message}
                if conversation:
                    payload['conversationId'] = str(conversation)
                started = time.perf_counter()
                frames, data_lines = [], []
                async with client.stream('POST', '/api/agent/chat/stream', json=payload) as response:
                    response.raise_for_status()
                    assert 'text/event-stream' in response.headers.get('content-type', ''), 'Not an SSE response'
                    async for line in response.aiter_lines():
                        if line.startswith('data:'):
                            data_lines.append(line[5:].removeprefix(' '))
                        elif not line and data_lines:
                            frames.append('\n'.join(data_lines))
                            data_lines = []
                if data_lines:
                    frames.append('\n'.join(data_lines))
                conv_frames = [f.split(':', 1)[1] for f in frames if f.startswith('__CONV_ID__:')]
                if conv_frames:
                    conversation = int(conv_frames[-1])
                row = await db.fetch_one('SELECT run_id,conversation_id,status,result_json FROM agent_run WHERE user_id=:uid AND request_id=:request',
                                         {'uid': uid, 'request': request_id})
                assert row is not None, 'Website request did not create an owned Agent run'
                record = dict(row._mapping)
                conversation = int(record['conversation_id'])
                result = json.loads(record['result_json'] or '{}')
                snapshot = await saver.aget_tuple({'configurable': {'thread_id': 'run_' + record['run_id']}})
                state = snapshot.checkpoint.get('channel_values', {}) if snapshot else {}
                reply_frames = [json.loads(f.split(':', 1)[1])['content'] for f in frames if f.startswith('__REPLY__:')]
                answer = reply_frames[-1] if reply_frames else ''.join(
                    json.loads(f.split(':', 1)[1]).get('content', '') for f in frames
                    if f.startswith('__ANSWER__:') and json.loads(f.split(':', 1)[1]).get('type') == 'delta')
                metrics = result.get('metrics', {})
                checks = {'sse_done': '[DONE]' in frames, 'no_error_frame': not any(f.startswith('[ERROR]') for f in frames),
                          'run_succeeded': record['status'] == 'succeeded', 'reply_present': bool(answer),
                          'redis_checkpoint_present': snapshot is not None, 'provider_usage_recorded':
                          metrics.get('llm_calls', 0) > 0 and metrics.get('measured_input_tokens', 0) > 0}
                context = state.get('task_context') or {}
                active = context.get('active_requirements', [])
                active_quotes = '\n'.join(item.get('quote', '') for item in active)
                if case_id == 'requirements_initial':
                    checks['structured_requirements_saved'] = all(value in active_quotes
                        for value in ('灯塔-N9', '中文', '表格', '2026-11-10', 'Java 17'))
                else:
                    checks['revocation_saved'] = bool(context.get('revoked_requirements'))
                    checks['changed_requirement_active'] = '2026-11-20' in active_quotes
                    checks['changed_requirement_old_id_inactive'] = all(
                        item['id'] not in {old['id'] for old in context.get('revoked_requirements', [])}
                        for item in active)
                if case_id.startswith('requirements_final'):
                    try:
                        parsed = json.loads(answer.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
                    except ValueError:
                        parsed = None
                    checks['active_requirements_correct'] = parsed == {'project': '灯塔-N9', 'language': '中文',
                        'format': '三条列表', 'deadline': '2026-11-20', 'stack': 'Java 17'}
                case = {'id': case_id, 'request_id': request_id, 'run_id': record['run_id'],
                        'conversation_id': str(conversation), 'elapsed_ms': round((time.perf_counter()-started)*1000),
                        'reply': answer, 'checks': checks, 'passed': all(checks.values()), 'metrics': metrics,
                        'checkpoint_task_context': state.get('task_context'),
                        'sse_markers': sorted({f.split(':', 1)[0] for f in frames if f.startswith('__')})}
                report['cases'].append(case)
                save(report_path, report)
                print(json.dumps({k: case[k] for k in ('id', 'run_id', 'checks', 'elapsed_ms', 'passed')}, ensure_ascii=False), flush=True)
                assert case['passed'], 'Website context check failed: ' + case_id
            history = await client.get(f'/api/agent/conversations/{conversation}/messages?limit=20')
            history.raise_for_status()
            history_body = history.json()
            items = (history_body.get('data') or {}).get('items', [])
            report['history_checks'] = {
                'http_success': history_body.get('code') == 200,
                'original_user_messages_preserved': [i.get('content') for i in items if i.get('role') == 'user']
                    == [message for _, message in prompts],
                'original_replies_preserved': [i.get('content') for i in items if i.get('role') == 'assistant']
                    == [case['reply'] for case in report['cases']],
            }
            report['history_round_trip'] = all(report['history_checks'].values())
            save(report_path, report)
            assert report['history_round_trip'], 'Persisted website history differs from the live stream'
            if result_recovery:
                case = await result_recovery_case(client, saver, uid)
                report['cases'].append(case)
                save(report_path, report)
                print(json.dumps({k: case[k] for k in ('id', 'run_id', 'checks', 'elapsed_ms', 'passed')}, ensure_ascii=False), flush=True)
                assert case['passed'], 'State-local result read failed after actual HTTP recovery'
        except BaseException as error:
            report['failure_type'] = type(error).__name__
            save(report_path, report)
            raise
        finally:
            # Identity and ownership checks precede every cleanup. No broad table clears.
            owner = await db.fetch_val('SELECT email FROM user_info WHERE user_id=:uid', {'uid': uid})
            assert owner in (None, email), 'Fixture identity changed; cleanup stopped'
            runs = await db.fetch_all('SELECT run_id,status FROM agent_run WHERE user_id=:uid', {'uid': uid})
            assert all(r['status'] not in ('running', 'awaiting_approval') for r in runs), 'Fixture run still active; cleanup stopped'
            conversations = await db.fetch_all('SELECT conversation_id FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
            for item in conversations:
                cid = item['conversation_id']
                await client.delete(f'/api/agent/conversations/{cid}')
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid': cid})
            for item in runs:
                rid = item['run_id']
                await saver.adelete_thread('run_' + rid)
                for table in ('agent_stream_frame', 'agent_run_event', 'agent_answer_feedback'):
                    await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid': rid})
            await db.execute('DELETE FROM agent_background_job WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM agent_run WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
            await revoke_sessions([uid])
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': email})
            report['cleanup'] = True
            save(report_path, report)
            await saver.__aexit__(None, None, None)
            await redis.aclose()
            await db.disconnect()
    print(json.dumps({'report': str(report_path.resolve()), 'cases': len(report['cases']), 'cleanup': report['cleanup']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--result-recovery', action='store_true')
    args = parser.parse_args()
    asyncio.run(run(args.output, args.result_recovery))
