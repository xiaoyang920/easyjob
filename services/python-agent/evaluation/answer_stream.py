"""Synthetic real-model smoke for direct streaming; no app data or tool writes."""
import os
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import argparse
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

CASES = [
    ('greeting', '你好，简单介绍一下你能做什么，三句话即可。'),
    ('concept', '不用搜索，用三段文字解释RAG的基本原理，以及它为什么不能完全消除幻觉。'),
    ('example', '不用搜索，写一个Python列表去重的简单示例，保留原来的元素顺序，并解释两句。'),
]


async def run_case(case_id, question):
    from langgraph.checkpoint.memory import InMemorySaver
    from app import main
    from app.graph import builder
    from app.graph.state_factory import create_initial_state
    from app.services.memory_policy import memory_policy_service
    graph = None
    model_ids, model_ends, deltas, errors = set(), [], [], []
    diagnostic = {'model_chunks': 0, 'eligible_chunks': 0, 'tool_names': [], 'argument_parts': []}
    first_text, settled = None, None
    started = time.perf_counter()

    class ObservedGraph:
        async def astream_events(self, *args, **kwargs):
            async for event in graph.astream_events(*args, **kwargs):
                if event['event'] == 'on_chat_model_start':
                    model_ids.add(event['run_id'])
                elif event['event'] == 'on_chat_model_end':
                    model_ends.append(time.perf_counter())
                elif event['event'] == 'on_chat_model_stream':
                    diagnostic['model_chunks'] += 1
                    diagnostic['eligible_chunks'] += int(event.get('metadata', {}).get('public_answer_stream') is True)
                    for part in getattr(event.get('data', {}).get('chunk'), 'tool_call_chunks', []) or []:
                        if part.get('name'):
                            diagnostic['tool_names'].append(part['name'])
                        diagnostic['argument_parts'].append(part.get('args') or '')
                yield event

        async def aget_state(self, *args, **kwargs):
            return await graph.aget_state(*args, **kwargs)

    async def finish(conv_id, user_id, snapshot, config):
        nonlocal settled
        settled = time.perf_counter()
        return {'reply': snapshot.values.get('final_reply', ''), 'articles': [], 'citations': [],
                'interrupted': None, 'cancelled': False, 'draft_article_id': None}

    blocked = AsyncMock(side_effect=RuntimeError('Synthetic streaming smoke forbids external actions'))
    auditor = AsyncMock(side_effect=RuntimeError('Synthetic direct cases must not invoke the auditor'))
    service = SimpleNamespace(finish=finish, repository=SimpleNamespace(
        fail=AsyncMock(), get=AsyncMock(return_value=None), assert_executor=AsyncMock()))
    config = {'configurable': {'thread_id': 'synthetic-stream-' + case_id, 'run_id': case_id, 'execution_token': 'fixture'}}
    with patch.object(main, 'run_service', service), \
         patch.object(builder, 'main_retrieve_node', blocked), \
         patch.object(builder, 'main_delegate_node', blocked), \
         patch.object(builder, 'prepare_draft', blocked), \
         patch.object(memory_policy_service, 'enqueue_changes', blocked), \
         patch('app.services.grounding.review_text', auditor):
        graph = builder._build_graph().compile(checkpointer=InMemorySaver())
        async for frame in main._stream_source(ObservedGraph(), create_initial_state(0, question, []), 0, 0, config):
            if frame.startswith('data:__ANSWER__:'):
                payload = json.loads(frame.removeprefix('data:__ANSWER__:').strip())
                if payload.get('type') == 'delta':
                    first_text = first_text or time.perf_counter()
                    deltas.append(payload['content'])
            elif frame.startswith('data:[ERROR]'):
                errors.append(frame.split('[ERROR]', 1)[1].strip())
        snapshot = await graph.aget_state(config)
    answer = snapshot.values.get('final_reply', '')
    try:
        header = json.loads(''.join(diagnostic.pop('argument_parts')))
        diagnostic['field_order'] = list(header)
        diagnostic['header'] = {k: v for k, v in header.items() if k not in ('reply', 'user_reply')}
    except (ValueError, TypeError):
        diagnostic['field_order'] = []
    checks = {
        'text_before_model_end': bool(first_text and model_ends and first_text < model_ends[0]),
        'text_before_settlement': bool(first_text and settled and first_text < settled),
        'single_model_call': len(model_ids) == 1,
        'exact_text': bool(answer) and ''.join(deltas) == answer,
        'no_external_actions_or_audit': blocked.await_count == 0 and auditor.await_count == 0,
        'no_errors': not errors,
    }
    return {'id': case_id, 'checks': checks, 'passed': all(checks.values()), 'chunks': len(deltas),
            'first_text_ms': round((first_text - started) * 1000, 2) if first_text else None,
            'total_ms': round((time.perf_counter() - started) * 1000, 2), 'reply': answer,
            'diagnostic': diagnostic}


async def run(output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case_id, question in CASES:
        results.append(await run_case(case_id, question))
    (output / 'predictions.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in results), encoding='utf-8')
    summary = {'cases': len(results), 'passed': sum(r['passed'] for r in results),
               'scope': 'synthetic_direct_answer_streaming_no_database_or_tools',
               'note': 'Three smoke cases validate delivery timing, not factual accuracy or general performance.'}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args().output)))
