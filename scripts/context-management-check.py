"""Synthetic prompt-size comparison plus optional read-only SQL integration checks."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))


def benchmark():
    from app.config import settings
    from app.graph.state_factory import create_initial_state
    from app.graph.main_agent import build_main_messages, MainDecision
    from app.utils.context_budget import request_tokens
    state = create_initial_state(1, '比较这三次读取结果', [])
    state['task_results'] = {f'source_{i}': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
        'retrieval_target': 'knowledge', 'result': word * 20000, 'citations': [], 'article_cards': []}
        for i, word in enumerate(('alpha ', 'beta ', 'gamma '))}
    with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1000000):
        before = request_tokens(build_main_messages(state, {}), [MainDecision])
    messages = build_main_messages(state, {})
    after = request_tokens(messages, [MainDecision])
    view = json.loads(messages[1].content)['successful_tasks']
    assert after < before and all(len(r['result']) >= 100000 for r in state['task_results'].values())
    return {'fixture': 'synthetic_three_public_results', 'before_input_tokens': before,
            'after_input_tokens': after, 'reduction_percent': round((before - after) * 100 / before, 1),
            'indexed_results': sum(r.get('content_scope') == 'index_only' for r in view.values()),
            'real_model_calls': 0, 'raw_results_preserved': True}


async def live_checks():
    from app.clients.mysql_client import db
    from app.models.main_tool import tool_call_adapter, task_fields
    from app.graph.staged_plan import ExecutionTask
    from app.security.capabilities import task_capabilities
    from app.services.context_tools import conversation_history
    from app.services.conversation import ConversationService
    from app.services.run_history import RunHistory
    await db.connect()
    try:
        row = await db.fetch_one('''SELECT c.conversation_id,c.user_id,m.message_id FROM ai_conversation c
            JOIN ai_message m ON m.conversation_id=c.conversation_id
            WHERE c.status=1 AND CHAR_LENGTH(m.content)>0 ORDER BY m.message_id DESC LIMIT 1''')
        if not row: return {'skipped': 'no_owned_conversation_fixture'}
        cid, uid, mid = (row._mapping[k] for k in ('conversation_id', 'user_id', 'message_id'))
        call = tool_call_adapter.validate_python({'name': 'read_conversation_messages',
            'args': {'message_ids': [int(mid)], 'max_chars': 200}})
        task = ExecutionTask(task_id='probe', actor='main', **task_fields(call))
        context = {'user_id': int(uid), 'conversation_id': int(cid), 'current_task': task.model_dump(),
            'execution_mode': 'direct', 'capabilities': sorted(task_capabilities(task))}
        read = json.loads((await conversation_history(context))['result'])
        assert read['messages'][0]['message_id'] == str(mid)
        history = await ConversationService()._load_context(int(cid))
        stored = await RunHistory().task_context(int(cid), int(uid), 'read-only-probe')
        assert isinstance(stored, dict) and history
        keyword = read['messages'][0]['content'][:2].strip() or '历史'
        call = tool_call_adapter.validate_python({'name': 'search_conversation_history',
            'args': {'keyword': keyword, 'limit': 1}})
        task = ExecutionTask(task_id='search_probe', actor='main', **task_fields(call))
        context['current_task'] = task.model_dump()
        search = json.loads((await conversation_history(context))['result'])
        assert isinstance(search['messages'], list)
        return {'message_reader': True, 'history_search': True, 'paged_loader': True,
                'task_context_sql': True, 'business_writes': False}
    finally:
        await db.disconnect()


if __name__ == '__main__':
    report = {'benchmark': benchmark()}
    if '--live-read-only' in sys.argv:
        report['sql_checks'] = asyncio.run(live_checks())
    path = ROOT / 'temp/context-management-check.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
