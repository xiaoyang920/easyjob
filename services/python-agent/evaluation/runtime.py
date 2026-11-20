"""Deterministic cost probes and an opt-in isolated SQL/Redis process-kill test.

Never scores answer accuracy: fake providers deliberately avoid cloud calls.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from urllib.parse import quote

from app.config import settings
from app.services.query_vector_cache import QueryVectorCache
from app.services.query_rewrite import QueryRewriteService
from app.services.stream_coalescing import coalesce_previews, preview_delta


def delta(text):
    return 'data:__PREVIEW__:' + json.dumps({'type': 'delta', 'content': text, 'provisional': True}, ensure_ascii=False) + '\n\n'


async def cost_probes():
    queries = [f'Redis 缓存一致性策略 {i}' for i in range(48)]
    cache = QueryVectorCache(capacity=512, ttl=600)
    calls = 0
    async def provider():
        nonlocal calls
        calls += 1
        await asyncio.sleep(.002)
        return [1., 0., 0., 1.]
    for _ in range(8):
        await asyncio.gather(*(cache.get_or_compute('fixture-model', query, 4, provider) for query in queries))
    assert calls == 48
    service = QueryRewriteService.__new__(QueryRewriteService)
    service.rewrite = AsyncMock(return_value={'status': 'rewritten'})
    for query in queries:
        await service.rewrite_request({'instruction': query, 'search_query': query, 'filters': {}}, query, [])
    bypass_model_calls = service.rewrite.await_count
    # Unresolved references and filters still use the model stage.
    for _ in range(8):
        await service.rewrite_request({'instruction': '解释它', 'search_query': '它的原理', 'filters': {}}, '解释它', [])
    assert service.rewrite.await_count == 8 and bypass_model_calls == 0
    texts = [('中文😀\n' if i % 10 == 0 else '内容') for i in range(1000)]
    async def source():
        for text in texts:
            yield delta(text)
            await asyncio.sleep(.002)
        yield 'data:__PROGRESS__:done\n\n'
        yield 'data:[DONE]\n\n'
    started = time.perf_counter()
    output, first_ms = [], None
    async for frame in coalesce_previews(source(), interval=.12):
        if first_ms is None: first_ms = (time.perf_counter() - started) * 1000
        output.append(frame)
    actual = ''.join(preview_delta(f)['content'] for f in output if preview_delta(f))
    assert actual == ''.join(texts) and output[-1] == 'data:[DONE]\n\n'
    return {'scope': 'offline synthetic providers; no model latency or answer-quality measurement',
            'query_rewrite': {'resolved_cases': 48, 'extra_model_calls': bypass_model_calls, 'ambiguous_cases_rewritten': 8},
            'embedding': {'requests': 384, 'provider_calls_without_cache': 384, 'provider_calls_with_cache': calls,
                          'hits': cache.hits, 'coalesced': cache.coalesced, 'saved_calls': 384 - calls},
            'stream': {'incoming_frames': 1002, 'persisted_frames_after_coalescing': len(output),
                       'text_identical': True, 'first_frame_ms': round(first_ms, 3), 'interval_ms': 120}}


def probe_graph(saver, folder, phase):
    from langgraph.graph import StateGraph, START, END
    from app.graph.state import AgentState
    from app.graph import action_runtime as actions, staged_runtime as runtime
    # The actual scheduler, artifact store and fencing run against live SQL/Redis;
    # only the external worker is replaced with a deterministic provider.
    async def worker(context):
        task_id = context['task_id']
        with (folder / 'worker-calls.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps({'task': task_id, 'phase': phase}) + '\n')
        if phase == 'first' and task_id == 'b':
            (folder / 'ready').touch()
            await asyncio.Event().wait()
        return {'task_results': {task_id: {'task_id': task_id, 'actor': 'subagent',
                'kind': context['current_task']['kind'], 'status': 'succeeded',
                'result': f'Synthetic result {task_id}', 'citations': [], 'article_cards': []}}}
    async def delegate(state):
        with patch.object(runtime, 'subagent_node', worker):
            return await actions.main_delegate_node(state)
    graph = StateGraph(AgentState)
    graph.add_node('main_delegate', runtime.guard_node('main_delegate', delegate))
    graph.add_edge(START, 'main_delegate'); graph.add_edge('main_delegate', END)
    return graph.compile(checkpointer=saver)


def redis_url():
    password = f':{quote(settings.REDIS_STACK_PASSWORD, safe="")}@' if settings.REDIS_STACK_PASSWORD else ''
    return f'redis://{password}{settings.REDIS_STACK_HOST}:{settings.REDIS_STACK_PORT}/{settings.REDIS_STACK_DB}'


async def child(args):
    from app.clients.mysql_client import db
    from app.services.run_repository import run_repository
    from app.services.run_service import RunService
    from app.graph.state_factory import create_initial_state
    from app.graph.staged_plan import ExecutionTask, ExecutionPlan
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    await db.connect()
    try:
        async with AsyncRedisSaver(redis_url=redis_url()) as saver:
            graph = probe_graph(saver, args.output, args.worker)
            run = await run_repository.get(args.run_id)
            config = RunService.config(run)
            state = None
            if args.worker == 'first':
                state = create_initial_state(run['user_id'], 'isolated recovery probe', [])
                state.update(run_id=run['run_id'], conversation_id=run['conversation_id'], execution_token=run['execution_token'],
                    main_round=2, main_action='delegate', plan=ExecutionPlan(tasks=[
                        ExecutionTask(task_id='a', kind='search', actor='subagent', instruction='synthetic retrieval'),
                        ExecutionTask(task_id='b', kind='analysis', actor='subagent', instruction='synthetic comparison', depends_on=['a'])]).model_dump())
            result = await graph.ainvoke(state, config)
            assert set(result['task_results']) == {'a', 'b'} and result['main_round'] == 2
            from app.services.run_metrics import metrics_from
            await run_repository.settle(run['conversation_id'], run['user_id'], run['run_id'], run['execution_token'],
                'succeeded', {'reply': 'Synthetic completion', 'metrics': metrics_from(config)})
            await run_repository.release_admission(run['run_id'])
    finally: await db.disconnect()


async def fault_probe(folder):
    from app.clients.mysql_client import db
    from app.services.run_repository import run_repository
    from app.services.run_service import RunService
    from app.services.conversation import ConversationService
    from app.services.execution_admission import execution_admission
    from app.utils.snowflake import SnowflakeGenerator
    from fastapi import HTTPException
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    # Refuse to create fixtures or kill workers against a remote deployment.
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}
    assert settings.REDIS_STACK_HOST in {'localhost', '127.0.0.1', '::1'}
    async with AsyncRedisSaver(redis_url=redis_url()):
        pass  # Preflight before creating SQL fixtures.
    ids = SnowflakeGenerator(worker_id=26)
    uid, cid, rid = ids.next_id(), ids.next_id(), str(uuid4())
    email = f'agent-recovery-{rid}@example.invalid'
    process, ticket = None, None
    await db.connect()
    try:
        await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count,data_source)
            VALUES(:uid,'恢复测试',:email,'disabled-local-probe',NOW(),2,1,0,0,1,1,0,0,0,'evaluation')""", {'uid': uid, 'email': email})
        await db.execute("""INSERT INTO ai_conversation(conversation_id,user_id,title,status,create_time,update_time)
            VALUES(:cid,:uid,'isolated recovery probe',1,NOW(),NOW())""", {'cid': cid, 'uid': uid})
        # Recovery preserves a charged budget; it must not restart from zero.
        run, _ = await run_repository.create(cid, uid, str(uuid4()), 'fixture-input-hash')
        rid = run['run_id']
        await run_repository.persist_metrics(rid, run['execution_token'], {'budget_charged_tokens': 2000, 'llm_calls': 2})
        def start(phase):
            log = (folder / f'{phase}-worker.log').open('wb')
            try:
                return subprocess.Popen([sys.executable, '-m', 'evaluation.runtime', '--worker', phase,
                                         '--run-id', rid, '--output', str(folder)], stdout=log, stderr=log,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            finally: log.close()
        process = start('first')
        deadline = time.monotonic() + 45
        while not (folder / 'ready').exists():
            if process.poll() is not None: raise RuntimeError('测试进程提前退出，请查看 first-worker.log')
            if time.monotonic() > deadline: raise TimeoutError('恢复探针初始化超时')
            await asyncio.sleep(.1)
        process.kill()  # Only the Popen child created by this probe; never the application service.
        await asyncio.to_thread(process.wait, 5)
        process = None
        assert await db.fetch_val('SELECT COUNT(*) FROM agent_task_artifact WHERE run_id=:rid', {'rid': rid}) == 1
        await db.execute('UPDATE agent_run SET executor_lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid', {'rid': rid})
        assert await run_repository.expire_existing(cid, uid, rid)
        async with AsyncRedisSaver(redis_url=redis_url()) as saver:
            graph = probe_graph(saver, folder, 'resume')
            service = RunService(ConversationService(), SimpleNamespace())
            ticket = await execution_admission.acquire(uid)
            _, config = await service.prepare_recovery(rid, uid, graph, ticket)
            ticket = config['configurable']['admission_ticket']
            try:
                await service.prepare_recovery(rid, uid, graph, 'unused-ticket')
            except HTTPException as error: assert error.status_code == 409
            else: raise AssertionError('重复恢复没有被拦截')
        process = start('resume')
        code = await asyncio.to_thread(process.wait, 30)
        process = None
        if code: raise RuntimeError('恢复失败，请查看 resume-worker.log')
        run = await run_repository.get(rid)
        calls = [json.loads(line)['task'] for line in (folder / 'worker-calls.jsonl').read_text(encoding='utf-8').splitlines()]
        assert calls == ['a', 'b', 'b'] and run['status'] == 'succeeded' and run['recovery_count'] == 1
        assert json.loads(run['result_json'])['metrics']['budget_charged_tokens'] >= 2000
        return {'scope': 'isolated synthetic delegated graph; real local MySQL + Redis, no LLM calls',
                'process_hard_killed': True, 'worker_executions': calls, 'completed_task_reused': True,
                'unfinished_task_reexecuted': True, 'duplicate_recovery_rejected': True,
                'run_status': run['status'], 'recovery_count': run['recovery_count'], 'previous_budget_preserved': True}
    finally:
        if process is not None and process.poll() is None:
            process.kill(); await asyncio.to_thread(process.wait, 5)
        if ticket: await execution_admission.release(ticket)
        # Fixture identity is checked before deleting only this account's rows.
        if await db.fetch_val('SELECT email FROM user_info WHERE user_id=:uid', {'uid': uid}) == email:
            try:
                async with AsyncRedisSaver(redis_url=redis_url()) as saver:
                    await saver.adelete_thread('run_' + rid)
            finally:
                await db.execute('DELETE FROM agent_run_event WHERE run_id=:rid', {'rid': rid})
                await db.execute('DELETE FROM agent_stream_frame WHERE run_id=:rid', {'rid': rid})
                await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid', {'rid': rid, 'uid': uid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': email})
        await db.disconnect()


async def main(args):
    if args.worker:
        await child(args)
        return
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'cost_probes': await cost_probes()}
    if args.live_fault: result['fault_probe'] = await fault_probe(args.output)
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-fault', action='store_true', help='create local test fixtures, kill only an isolated probe child')
    parser.add_argument('--worker', choices=['first', 'resume'], help=argparse.SUPPRESS)
    parser.add_argument('--run-id', help=argparse.SUPPRESS)
    asyncio.run(main(parser.parse_args()))
