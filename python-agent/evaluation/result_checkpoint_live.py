"""Actual Redis graph breakpoint/resume in separate Python processes; no LLM.

Uses an isolated evaluation thread, not a production business run or account.
Run --phase seed first, then --phase resume with the same new output directory.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from redis.asyncio import Redis
from app.config import settings
from app.graph.action_runtime import execute_tool_node
from app.graph.state import AgentState
from app.graph.state_factory import create_initial_state
from app.graph.staged_plan import ExecutionTask
from app.models.main_tool import tool_call_adapter, task_fields
from app.services.checkpoint_store import LatestRunRedisSaver


def initial_state():
    state = create_initial_state(7, '读取已有结果，不联网', [])
    call = tool_call_adapter.validate_python({'name': 'read_task_results', 'args': {'requests': [
        {'source_task_id': 'long_log', 'query': '验收口令', 'max_chars': 1000},
        {'source_task_id': 'other', 'max_chars': 500}]}})
    task = ExecutionTask(task_id='readback', actor='main', **task_fields(call))
    state.update(plan={'tasks': [task.model_dump()]}, action_task_ids=['readback'], execution_mode='direct')
    state['task_results'] = {tid: {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
        'retrieval_target': 'knowledge', 'result': body, 'citations': [], 'article_cards': []}
        for tid, body in {'long_log': 'ordinary log ' * 8500 + '\n验收口令：恢复-K8P2\n', 'other': 'SECOND-SOURCE'}.items()}
    return state


def build(saver, checks):
    graph = StateGraph(AgentState)
    graph.add_node('persist_input', lambda state: {})
    async def read(state):
        before = checks.get('checkpoint_reads', 0)
        output = await execute_tool_node(state)
        checks['read_tool_did_not_query_checkpointer'] = before == checks.get('checkpoint_reads', 0)
        return output
    graph.add_node('execute_tool', read)
    graph.add_edge(START, 'persist_input')
    graph.add_edge('persist_input', 'execute_tool')
    graph.add_edge('execute_tool', END)
    return graph.compile(checkpointer=saver, interrupt_before=['execute_tool'])


async def run(phase, output):
    assert settings.REDIS_STACK_HOST in ('127.0.0.1', 'localhost', '::1'), 'Local checkpoint only'
    checks = {'phase': phase, 'real_redis': True, 'llm_calls': 0, 'business_run': False}
    if phase == 'seed':
        output.mkdir(parents=True, exist_ok=False)
        thread = 'eval_result_access_' + uuid4().hex
        (output/'manifest.json').write_text(json.dumps({'thread_id': thread}), encoding='utf-8')
    else:
        thread = json.loads((output/'manifest.json').read_text(encoding='utf-8'))['thread_id']
    assert re.fullmatch(r'eval_result_access_[a-f0-9]{32}', thread), 'Exact fixture thread only'
    redis = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT, db=settings.REDIS_STACK_DB,
                  password=settings.REDIS_STACK_PASSWORD or None)
    async with LatestRunRedisSaver(redis_client=redis) as saver:
        getter = saver.aget_tuple
        async def counted(config):
            checks['checkpoint_reads'] = checks.get('checkpoint_reads', 0) + 1
            return await getter(config)
        saver.aget_tuple = counted
        graph = build(saver, checks)
        config = {'configurable': {'thread_id': thread}}
        try:
            if phase == 'seed':
                await graph.ainvoke(initial_state(), config)
                snapshot = await graph.aget_state(config)
                assert snapshot.next == ('execute_tool',)
                assert 'readback' not in snapshot.values['task_results']
                checks['stopped_before_read'] = True
            else:
                snapshot = await graph.aget_state(config)
                expected = initial_state()['task_results']
                assert snapshot.values['task_results'] == expected
                checks['full_results_restored_from_redis'] = True
                restored = await graph.ainvoke(None, config)
                saved = restored['task_results']['readback']
                assert saved['status'] == 'succeeded'
                payload = json.loads(saved['result'])['results']
                assert '恢复-K8P2' in payload[0]['content']
                assert payload[1]['content'] == 'SECOND-SOURCE'
                assert restored['task_results']['long_log'] == expected['long_log']
                checks.update(exact_read_after_process_restart=True, original_result_unchanged=True,
                              read_metadata_persisted=bool(saved.get('result_reads')))
                after = await graph.aget_state(config)
                assert after.values['task_results']['readback']['result_reads'] == saved['result_reads']
                checks['original_sha256'] = hashlib.sha256(expected['long_log']['result'].encode()).hexdigest()
        finally:
            if phase == 'resume':
                await saver.adelete_thread(thread)
                checks['fixture_thread_deleted'] = (await getter(config)) is None
            (output/f'{phase}.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    await redis.aclose()
    print(json.dumps(checks), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('seed', 'resume'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.phase, args.output))
