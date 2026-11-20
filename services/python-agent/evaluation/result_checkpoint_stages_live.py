"""Two-process Redis continuation before/after reads and before final assembly."""
import argparse
import asyncio
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


def task(task_id, cursor=None):
    args = {'source_task_id': 'source', 'query': 'needle', 'max_chars': 500}
    if cursor: args['cursor'] = cursor
    call = tool_call_adapter.validate_python({'name': 'read_task_result', 'args': args})
    return ExecutionTask(task_id=task_id, actor='main', **task_fields(call)).model_dump()


def initial():
    state = create_initial_state(7, '读取合成结果中的后续命中，不联网', [])
    state.update(plan={'tasks': [task('read_first')]}, action_task_ids=['read_first'], main_action='call_tool')
    state['task_results'] = {'source': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
        'retrieval_target': 'knowledge', 'result': ''.join(f'needle={i}\n' + 'padding ' * 300 for i in range(10)),
        'citations': [], 'article_cards': []}}
    return state


def graph(saver, point, checks):
    builder = StateGraph(AgentState)
    async def read(state):
        checks['executed_reads'] = checks.get('executed_reads', 0) + 1
        return await execute_tool_node(state)
    def advance(state):
        payload = json.loads(state['task_results']['read_first']['result'])
        assert payload['next_cursor']
        return {'plan': {'tasks': [task('read_next', payload['next_cursor'])]}, 'action_task_ids': ['read_next']}
    def answer(state):
        first, second = (json.loads(state['task_results'][name]['result']) for name in ('read_first', 'read_next'))
        assert 'needle=0' in first['content'] and 'needle=1' in second['content']
        assert second['start_char'] > first['start_char']
        return {'final_reply': 'cursor-resume-ok'}
    builder.add_node('persist', lambda state: {})
    builder.add_node('read', read); builder.add_node('advance', advance)
    builder.add_node('read_next', read); builder.add_node('answer', answer)
    builder.add_edge(START, 'persist'); builder.add_edge('persist', 'read')
    builder.add_edge('read', 'advance'); builder.add_edge('advance', 'read_next')
    builder.add_edge('read_next', 'answer'); builder.add_edge('answer', END)
    return builder.compile(checkpointer=saver, interrupt_before=[point])


async def run(phase, output):
    assert settings.REDIS_STACK_HOST in ('127.0.0.1', 'localhost', '::1')
    if phase == 'seed':
        output.mkdir(parents=True, exist_ok=False)
        manifest = {'threads': {point: 'eval_context_stages_' + uuid4().hex for point in ('read', 'advance', 'answer')}}
        (output/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    else:
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    client = Redis(host=settings.REDIS_STACK_HOST, port=settings.REDIS_STACK_PORT, db=settings.REDIS_STACK_DB,
                   password=settings.REDIS_STACK_PASSWORD or None)
    report = {'phase': phase, 'real_redis': True, 'business_runs': False, 'model_calls': 0, 'cases': []}
    try:
        async with LatestRunRedisSaver(redis_client=client) as saver:
            for point, thread in manifest['threads'].items():
                assert re.fullmatch(r'eval_context_stages_[a-f0-9]{32}', thread)
                checks = {'point': point}
                compiled = graph(saver, point, checks)
                config = {'configurable': {'thread_id': thread}}
                if phase == 'seed':
                    await compiled.ainvoke(initial(), config)
                    snapshot = await compiled.aget_state(config)
                    checks['passed'] = snapshot.next == (point,)
                else:
                    before = await compiled.aget_state(config)
                    assert before.next == (point,)
                    result = await compiled.ainvoke(None, config)
                    expected_reads = {'read': 2, 'advance': 1, 'answer': 0}[point]
                    checks.update(completed=result['final_reply'] == 'cursor-resume-ok',
                        no_completed_read_repeated=checks.get('executed_reads', 0) == expected_reads,
                        source_unchanged=result['task_results']['source'] == initial()['task_results']['source'],
                        cursor_metadata_preserved=bool(result['task_results']['read_next']['result_reads']))
                    await saver.adelete_thread(thread)
                    checks['fixture_deleted'] = await saver.aget_tuple(config) is None
                    checks['passed'] = all(checks[key] for key in ('completed', 'no_completed_read_repeated',
                        'source_unchanged', 'cursor_metadata_preserved', 'fixture_deleted'))
                report['cases'].append(checks)
                (output/f'{phase}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                assert checks['passed']
    finally:
        await client.aclose()
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('seed', 'resume'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.phase, args.output.resolve()))
