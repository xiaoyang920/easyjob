"""Isolated local HTTP, SQL and Redis checks, including two-process summary recovery.

seed creates one disposable identity and a real compacted conversation checkpoint.
resume logs in as that fixture, recovers through the website, and deletes it.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import secrets
import time
from uuid import uuid4

import httpx
from redis.asyncio import Redis

from app.clients.mysql_client import db
from app.config import settings
from app.services.checkpoint_store import LatestRunRedisSaver
from app.utils.snowflake import SnowflakeGenerator
from evaluation.context_http_live import save
from evaluation.context_live import parse_json
from evaluation.fixture_cleanup import revoke_sessions


@asynccontextmanager
async def resources():
    assert db.url.hostname in ('127.0.0.1', 'localhost', '::1')
    assert settings.REDIS_STACK_HOST in ('127.0.0.1', 'localhost', '::1')
    await db.connect()
    redis = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT, db=settings.REDIS_STACK_DB,
                  password=settings.REDIS_STACK_PASSWORD or None)
    async with LatestRunRedisSaver(redis_client=redis) as saver:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:3000', trust_env=False,
                                     timeout=httpx.Timeout(240, connect=10)) as client:
            try:
                yield saver, client
            finally:
                await redis.aclose()
                await db.disconnect()


async def identity():
    uid = SnowflakeGenerator(worker_id=28).next_id()
    email = 'context-next-' + uuid4().hex + '@example.invalid'
    await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,
        total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count,data_source)
        VALUES(:uid,:nickname,:email,:password,NOW(),2,1,0,0,1,1,0,0,0,'evaluation')''',
        {'uid': uid, 'nickname': 'ctxn-' + uuid4().hex[:10], 'email': email, 'password': secrets.token_urlsafe(28)})
    return {'user_id': uid, 'email': email}


async def login(client, fixture):
    row = await db.fetch_one('SELECT email,data_source FROM user_info WHERE user_id=:uid', {'uid': fixture['user_id']})
    assert row and row['email'] == fixture['email'] and row['data_source'] == 'evaluation'
    # Login migrates legacy plaintext to a hash. Rotate only this exact fixture's
    # ephemeral password, avoiding any credential in a cross-process manifest.
    password = secrets.token_urlsafe(28)
    await db.execute("UPDATE user_info SET password=:password WHERE user_id=:uid AND email=:email AND data_source='evaluation'",
        {'password': password, 'uid': fixture['user_id'], 'email': fixture['email']})
    response = await client.post('/api/auth/login', json={'email': row['email'], 'password': password})
    response.raise_for_status()
    body = response.json()
    assert body['code'] == 200
    client.headers['Authorization'] = 'Bearer ' + body['data']['token']
    client.cookies.clear()


async def cleanup(client, saver, fixture):
    uid = fixture['user_id']
    owner = await db.fetch_val('SELECT email FROM user_info WHERE user_id=:uid', {'uid': uid})
    assert owner == fixture['email'] and owner.startswith('context-next-') and owner.endswith('@example.invalid')
    runs = await db.fetch_all('SELECT run_id,status FROM agent_run WHERE user_id=:uid', {'uid': uid})
    assert not any(row['status'] in ('running', 'awaiting_approval') for row in runs), 'Fixture still active; cleanup stopped'
    articles = await db.fetch_all('''SELECT article_id FROM article_info WHERE user_id=:uid
        UNION SELECT article_id FROM article_revision WHERE author_id=:uid''', {'uid': uid})
    for row in articles:
        response = await client.delete('/api/article/' + str(row['article_id']))
        response.raise_for_status()
        assert response.json()['code'] == 200
        # Deletion is soft in the product. Remove only this disposable owner's
        # evaluation revisions and the audit rows created by the deletion.
        await db.execute('DELETE FROM article_review_log WHERE article_id=:aid AND actor_id=:uid',
                         {'aid': row['article_id'], 'uid': uid})
        await db.execute("DELETE FROM article_revision WHERE article_id=:aid AND author_id=:uid AND data_source='evaluation'",
                         {'aid': row['article_id'], 'uid': uid})
        await db.execute("DELETE FROM article_info WHERE article_id=:aid AND user_id=:uid AND data_source='evaluation'",
                         {'aid': row['article_id'], 'uid': uid})
    for row in await db.fetch_all('SELECT conversation_id FROM ai_conversation WHERE user_id=:uid', {'uid': uid}):
        await client.delete('/api/agent/conversations/' + str(row['conversation_id']))
        await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid', {'cid': row['conversation_id']})
    for row in runs:
        rid = row['run_id']
        await saver.adelete_thread('run_' + rid)
        for table in ('agent_stream_frame', 'agent_run_event', 'agent_answer_feedback', 'agent_task_artifact'):
            await db.execute(f'DELETE FROM {table} WHERE run_id=:rid', {'rid': rid})
        await db.execute('DELETE FROM article_agent_save_receipt WHERE run_id=:rid AND user_id=:uid', {'rid': rid, 'uid': uid})
    await db.execute('DELETE FROM agent_background_job WHERE user_id=:uid', {'uid': uid})
    await db.execute('DELETE FROM agent_run WHERE user_id=:uid', {'uid': uid})
    await db.execute('DELETE FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
    await revoke_sessions([uid])
    await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': fixture['email']})


async def stream(client, path, payload=None):
    frames, lines = [], []
    async with client.stream('POST', path, json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith('data:'):
                lines.append(line[5:].removeprefix(' '))
            elif not line and lines:
                frames.append('\n'.join(lines)); lines = []
    if lines: frames.append('\n'.join(lines))
    assert not any(frame.startswith('[ERROR]') for frame in frames), 'Error frame in fixture stream'
    return frames


async def seed(output):
    from app.graph.state_factory import create_initial_state
    from app.graph.main_agent import build_main_messages, MainDecision
    from app.services.conversation import ConversationService
    from app.services.run_repository import run_repository, digest
    from app.services.run_service import RunService
    from app.graph.builder import _build_graph
    from app.models.task_context import TaskContextPatch, update_task_context
    from app.utils.context_budget import request_tokens
    from app.utils.token_utils import count_tokens
    output.mkdir(parents=True, exist_ok=False)
    async with resources() as (saver, client):
        fixture = await identity()
        manifest = {**fixture, 'phase': 'seed', 'cleanup': False}
        save(output/'manifest.json', manifest)
        await login(client, fixture)
        service = ConversationService()
        cid = await service.create_conversation(fixture['user_id'])
        messages, generator = [], SnowflakeGenerator(worker_id=29)
        def add(role, content):
            messages.append({'message_id': generator.next_id(), 'role': role, 'content': content})
        first = '本次项目代号灯塔-N9，期限2026-11-10，不要自动缩进。'
        revision = '取消期限2026-11-10，改为2026-11-20。仍然不要自动缩进。'
        add('user', first); add('assistant', '收到，仅用于当前任务。')
        add('user', revision); add('assistant', '已按本次变更理解任务。')
        query = ('根据我已确认的当前要求，只返回JSON：project填项目代号，deadline填当前期限，'
                 'auto_indent填布尔值。不要搜索、写文章或修改长期记忆。')
        state = create_initial_state(fixture['user_id'], query, messages)
        block = 'debug event=healthy retry=0\n' * 900
        for _ in range(25):
            add('user', '这是无关旧日志，不改变要求。\n' + block)
            add('assistant', '只记录调试资料。\n' + block)
            state['history_messages'] = list(messages)
            tokens = request_tokens(build_main_messages(state, {}), [MainDecision])
            if tokens > 205000: break
        assert 196608 < tokens < 245760, 'Fixture must really cross the 192K trigger'
        await db.execute_many('''INSERT INTO ai_message(message_id,conversation_id,role,content,token_count,create_time)
            VALUES(:mid,:cid,:role,:content,:tokens,NOW())''', [
            {'mid': message['message_id'], 'cid': cid, 'role': message['role'], 'content': message['content'],
             'tokens': count_tokens(message['content'])} for message in messages])
        result = await service.compact_history(cid, messages, len(messages)-2, user_id=fixture['user_id'])
        assert result['status'] == 'compacted' and result['persisted']
        summary = result['history'][0]
        assert summary['summary_upto_msg_id'] == messages[-3]['message_id']
        mid = await service.add_message(cid, 'user', query, postprocess=False)
        run, _ = await run_repository.create(cid, fixture['user_id'], str(uuid4()), digest({'fixture': query}))
        await run_repository.record_input(run['run_id'], run['execution_token'], mid)
        state.update(run_id=run['run_id'], execution_token=run['execution_token'], conversation_id=cid,
            user_message_id=str(mid), history_messages=result['history'])
        context = update_task_context({**state, 'user_message': first, 'user_message_id': str(messages[0]['message_id'])},
            TaskContextPatch(requirements=[{'id': 'project', 'quote': '项目代号灯塔-N9'},
                {'id': 'old_deadline', 'quote': '期限2026-11-10'}, {'id': 'indent', 'quote': '不要自动缩进'}]))
        state['task_context'] = update_task_context({**state, 'task_context': context, 'user_message': revision,
            'user_message_id': str(messages[2]['message_id'])}, TaskContextPatch(
                revoke_requirement_ids=['old_deadline'], revocation_quote='取消期限2026-11-10',
                requirements=[{'id': 'new_deadline', 'quote': '改为2026-11-20'}]))
        graph = _build_graph().compile(checkpointer=saver)
        config = RunService.config(run)
        await graph.aupdate_state(config, state, as_node='main_delegate')
        await run_repository.fail(run['run_id'], run['execution_token'])
        manifest.update(conversation_id=cid, run_id=run['run_id'], original_tokens=tokens,
            after_tokens=request_tokens(build_main_messages(state, {}), [MainDecision]),
            summary_calls=result['summary_calls'], summary_usage=result['summary_usage'],
            summary_cursor=str(summary['summary_upto_msg_id']), history_count=len(messages),
            history_sha256=hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
            summary_sha256=hashlib.sha256(summary['content'].encode()).hexdigest(), ready_to_resume=True)
        save(output/'manifest.json', manifest)
        print(json.dumps({'phase': 'seed', 'original_tokens': tokens, 'after_tokens': manifest['after_tokens'],
                          'summary_calls': manifest['summary_calls'], 'ready_to_resume': True}), flush=True)


async def resume(output):
    from app.services.run_repository import run_repository
    fixture = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    assert fixture.get('ready_to_resume') and not fixture.get('cleanup')
    report = {'phase': 'resume', 'separate_process': True, 'checks': {}, 'cleanup': False}
    async with resources() as (saver, client):
        await login(client, fixture)
        try:
            snapshot = await saver.aget_tuple({'configurable': {'thread_id': 'run_' + fixture['run_id']}})
            state = snapshot.checkpoint['channel_values']
            before = state['history_messages'][0]
            report['checks']['summary_restored_from_redis'] = hashlib.sha256(before['content'].encode()).hexdigest() == fixture['summary_sha256']
            started = time.perf_counter()
            frames = await stream(client, '/api/agent/runs/' + fixture['run_id'] + '/recover')
            run = await run_repository.get(fixture['run_id'])
            result = json.loads(run['result_json'])
            replies = [json.loads(frame.split(':', 1)[1])['content'] for frame in frames if frame.startswith('__REPLY__:')]
            answer = replies[-1] if replies else result.get('reply', '')
            row = await db.fetch_one('SELECT summary,summary_upto_msg_id FROM ai_conversation WHERE conversation_id=:cid',
                                     {'cid': fixture['conversation_id']})
            report['checks'].update(same_run_succeeded=run['status'] == 'succeeded' and run['recovery_count'] > 0,
                active_requirements_correct=parse_json(answer) == {'project': '灯塔-N9', 'deadline': '2026-11-20', 'auto_indent': False},
                cursor_preserved=str(row['summary_upto_msg_id']) == fixture['summary_cursor'],
                summary_persisted_unchanged='[之前的对话摘要]\n' + row['summary'] == before['content'],
                provider_usage=(result.get('metrics') or {}).get('measured_input_tokens', 0) > 0)
            report.update(elapsed_ms=round((time.perf_counter()-started)*1000), reply=answer, metrics=result.get('metrics'),
                          passed=all(report['checks'].values()))
            assert report['passed'], 'Long-compaction cross-process recovery failed'
        finally:
            save(output/'resume.json', report)
            await cleanup(client, saver, fixture)
            report['cleanup'] = fixture['cleanup'] = True
            save(output/'manifest.json', fixture); save(output/'resume.json', report)
    print(json.dumps({k: report[k] for k in ('phase', 'checks', 'passed', 'cleanup', 'elapsed_ms')}, ensure_ascii=False))


def server_memory():
    """Read RSS only for the exact Agent process IDs recorded by the launcher."""
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged',
                                                        'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]]
    try:
        pids = json.loads(Path('temp/context-next-server-pids.json').read_text(encoding='utf-8-sig'))
        pids = pids if isinstance(pids, list) else [pids]
        kernel, psapi = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('psapi', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        total = 0
        for pid in pids:
            handle = kernel.OpenProcess(0x1000 | 0x10, False, int(pid))
            if not handle: return None
            try:
                values = Counters(); values.cb = ctypes.sizeof(values)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(values), values.cb): return None
                total += values.working
            finally:
                kernel.CloseHandle(handle)
        return total
    except (OSError, ValueError, AttributeError):
        return None


async def http_cases(output, *, approvals=True, concurrent=True):
    """Real website approvals and admitted 1/2/4 same-user concurrent runs."""
    output.mkdir(parents=True, exist_ok=False)
    report = {'phase': 'http', 'approvals_included': approvals, 'cases': [], 'cleanup': False,
              'execution_user_limit': settings.EXECUTION_USER_LIMIT,
              'server_memory_measurement': 'sum of exact Agent launcher/worker RSS, sampled; includes shared pages'}
    async with resources() as (saver, client):
        fixture = await identity()
        save(output/'manifest.json', fixture)
        await login(client, fixture)
        uid = fixture['user_id']
        async def chat(message, *, actor=None):
            request = str(uuid4())
            frames = await stream(client, '/api/agent/chat/stream', {'requestId': request, 'message': message})
            row = await db.fetch_one('SELECT * FROM agent_run WHERE user_id=:uid AND request_id=:request',
                                     {'uid': (actor or fixture)['user_id'], 'request': request})
            return frames, dict(row._mapping)
        try:
            for action in (('reject', 'approve') if approvals else ()):
                frames, run = await chat('请进入写草稿流程，为我新建一篇约100字的原创示例文章，标题为“上下文验收示例”。'
                    '只讲通用的整理笔记方法，不需要外部事实依据，不要检索或存长期记忆。生成后等待我确认，不能自动保存。')
                interrupts = [json.loads(frame.split(':', 1)[1]) for frame in frames if frame.startswith('__INTERRUPTED__:')]
                assert run['status'] == 'awaiting_approval' and len(interrupts) == 1
                pending = interrupts[0]
                count_before = await db.fetch_val('SELECT COUNT(DISTINCT article_id) FROM article_revision WHERE author_id=:uid AND deleted=0', {'uid': uid})
                # Ordinary recovery must not auto-replay a waiting write approval.
                blocked = await client.post('/api/agent/runs/' + run['run_id'] + '/recover')
                try: blocked_code = blocked.json().get('code')
                except ValueError: blocked_code = None
                assert blocked.status_code == 409 or blocked_code == 409
                saved_state = await saver.aget_tuple({'configurable': {'thread_id': 'run_' + run['run_id']}})
                assert saved_state and saved_state.pending_writes is not None
                decision = {'runId': run['run_id'], 'conversationId': str(run['conversation_id']),
                            'draftHash': pending['draftHash'], 'action': action}
                started = time.perf_counter()
                await stream(client, '/api/agent/chat/resume/stream', decision)
                after = await db.fetch_one('SELECT * FROM agent_run WHERE run_id=:rid', {'rid': run['run_id']})
                count_after = await db.fetch_val('SELECT COUNT(DISTINCT article_id) FROM article_revision WHERE author_id=:uid AND deleted=0', {'uid': uid})
                checks = {'waiting_checkpoint_restored': True, 'ordinary_recovery_refused': True,
                    'terminal_success': after['status'] == 'succeeded',
                    'writes_exactly_as_approved': count_after-count_before == (1 if action == 'approve' else 0),
                    'saved_id_matches_action': bool(after['draft_article_id']) == (action == 'approve')}
                # Repeat the exact decision; it must not create another draft.
                repeated = await client.post('/api/agent/chat/resume', json=decision)
                checks['repeat_created_no_extra_article'] = await db.fetch_val(
                    'SELECT COUNT(DISTINCT article_id) FROM article_revision WHERE author_id=:uid AND deleted=0', {'uid': uid}) == count_after
                if action == 'approve':
                    checks['one_save_receipt'] = await db.fetch_val('SELECT COUNT(*) FROM article_agent_save_receipt WHERE run_id=:rid',
                                                                  {'rid': run['run_id']}) == 1
                case = {'id': 'approval_' + action, 'run_id': run['run_id'], 'checks': checks,
                        'elapsed_ms': round((time.perf_counter()-started)*1000), 'repeat_http_status': repeated.status_code,
                        'passed': all(checks.values())}
                report['cases'].append(case); save(output/'report.json', report)
                assert case['passed']
            for concurrency in ((1, 2, 4) if concurrent else ()):
                # A fresh disposable identity per group stays below the existing
                # gateway's 12 AI actions/minute. Do not change production limits.
                group_fixture = await identity()
                original_auth = client.headers['Authorization']
                await login(client, group_fixture)
                async def one(index):
                    code = f'ISOLATED-{concurrency}-{index}-K8P2'
                    started = time.perf_counter()
                    frames, row = await chat('仅返回JSON对象：' + json.dumps({'code': code}) + '，不使用任何工具、不修改记忆。', actor=group_fixture)
                    replies = [json.loads(frame.split(':', 1)[1])['content'] for frame in frames if frame.startswith('__REPLY__:')]
                    return {'run_id': row['run_id'], 'conversation_id': str(row['conversation_id']),
                        'elapsed_ms': round((time.perf_counter()-started)*1000),
                        'passed': row['status'] == 'succeeded' and bool(replies) and parse_json(replies[-1]) == {'code': code}}
                try:
                    stopped, memory = asyncio.Event(), []
                    async def sample():
                        while not stopped.is_set():
                            value = server_memory()
                            if value is not None: memory.append(value)
                            await asyncio.sleep(.1)
                    sampling = asyncio.create_task(sample())
                    try:
                        rows = await asyncio.gather(*(one(index) for index in range(concurrency)), return_exceptions=True)
                        assert not any(isinstance(row, BaseException) for row in rows), 'Concurrent fixture request failed'
                    finally:
                        stopped.set()
                        await sampling
                finally:
                    await cleanup(client, saver, group_fixture)
                    client.headers['Authorization'] = original_auth
                case = {'id': f'concurrency_{concurrency}', 'runs': rows, 'passed': all(row['passed'] for row in rows)
                    and len({row['run_id'] for row in rows}) == concurrency
                    and len({row['conversation_id'] for row in rows}) == concurrency,
                    'memory_samples': len(memory), 'server_rss_min': min(memory) if memory else None,
                    'server_rss_max': max(memory) if memory else None}
                report['cases'].append(case); save(output/'report.json', report)
                assert case['passed']
            from evaluation.context_http_live import result_recovery_case
            case = await result_recovery_case(client, saver, uid, race=True)
            case['id'] = 'same_run_concurrent_recovery'
            report['cases'].append(case); save(output/'report.json', report)
            assert case['passed']
        finally:
            save(output/'report.json', report)
            await cleanup(client, saver, fixture)
            report['cleanup'] = True
            save(output/'report.json', report)
    print(json.dumps({'cases': len(report['cases']), 'passed': sum(case['passed'] for case in report['cases']),
                      'cleanup': report['cleanup']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('seed', 'resume', 'http', 'concurrency', 'recovery'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run({'seed': seed, 'resume': resume, 'http': http_cases,
                 'concurrency': lambda output: http_cases(output, approvals=False),
                 'recovery': lambda output: http_cases(output, approvals=False, concurrent=False)}[args.phase](args.output.resolve()))
