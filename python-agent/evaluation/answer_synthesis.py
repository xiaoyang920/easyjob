"""Smoke-test Main synthesis and delivery against seeded synthetic retrieval.

Live mode uses the actual Main model and actual delivery auditor/repairer.
Replay mode mocks those models while retaining Main contracts and final_gate.
No retrieval/action nodes, database access, real conversation or checkpoint.
"""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from evaluation.answer_synthesis_cases import cases
from evaluation.metrics import percentile


SCOPE = 'seeded_context_main_decision_and_delivery'
NOTE = ('固定行为断言是小样本冒烟检查，不是全链路准确率或独立事实标注。'
        '未测试实际检索、用户数据库、历史会话、工具执行、写作保存或长期记忆；回复质量仍需人工审读。')


def seeded_state(case):
    from app.graph.state_factory import create_initial_state
    citations = [{'id': f'retrieve_1:{i}', 'articleId': '', 'title': source['title'],
        'excerpt': source['text'], 'url': source.get('url', ''),
        'contentScope': source.get('content_scope', 'fixture_text')}
        for i, source in enumerate(case['sources'], 1)]
    contents = {citation['id']: source['text'] for citation, source in zip(citations, case['sources'])}
    report = {'assessment_owner': 'main', 'platform': {'status': 'found'}, 'web': {'status': 'not_requested'}}
    result = {'status': 'succeeded', 'kind': 'search', 'actor': 'main', 'retrieval_target': 'knowledge',
        'instruction': '预置独立编写的合成资料；不执行真实检索',
        'result': '\n\n'.join(f'[{citation["id"]}] {citation["title"]}\n{contents[citation["id"]]}' for citation in citations),
        'citations': citations, 'citation_contents': contents, 'article_cards': [], 'retrieval_report': report}
    return {**create_initial_state(0, case['query'], []), 'run_id': '', 'main_round': 1,
        'task_results': {'retrieve_1': result},
        'observations': [{'round': 1, 'action': 'retrieve', 'tasks': {'retrieve_1': 'succeeded'},
            'failures': {}, 'retrieval_report': report}],
        'action_history': [{'round': 1, 'action': 'retrieve', 'task_ids': ['retrieve_1'], 'fingerprints': ['synthetic-seed']}]}


def assertions_for(case, result, blocked_calls):
    reply = result.get('final_reply') or ''
    decision = result.get('main_decision') or {}
    checks = case.get('checks', {})
    assertions = {
        'answer_selected': decision.get('action') == 'answer' and result.get('main_action') == 'answer',
        'not_contract_stop': not result.get('stop_reason'),
        'delivery_review_completed': (result.get('grounding_audit') or {}).get('status') in ('verified', 'repaired'),
        'no_external_action_or_memory_write': not blocked_calls and not decision.get('memory_changes'),
        'no_omitted_placeholder': '此处内容未通过依据核验' not in reply and '内容已省略' not in reply,
        'forbidden_absent': all(text not in reply for text in checks.get('forbidden', [])),
        'required_present': all(text in reply for text in checks.get('required', [])),
        'term_groups_present': all(any(term in reply for term in group) for group in checks.get('all_any', [])),
        'seed_sentence_not_repeated': all(reply.count(text) <= maximum for text, maximum in checks.get('max_occurrences', {}).items()),
    }
    if case['category'] != 'resource_list':
        # Mentioning one title to attribute or correct it is legitimate. Only
        # flag obvious multi-source heading dumps, not every source reference.
        lines = [line.strip().lstrip('-*#0123456789.) ').strip() for line in reply.splitlines()]
        source_headings = sum(any(line.startswith(source['title']) for line in lines) for source in case['sources'])
        assertions['no_raw_source_dump'] = '来源摘录：' not in reply and source_headings < 2
    return assertions


async def execute(case, mode):
    if mode not in ('replay', 'live'):
        raise ValueError('mode必须为replay或live')
    from langgraph.graph import StateGraph, START, END
    from app.graph import main_agent, staged_runtime
    from app.graph.state import AgentState
    from app.models.evidence_assessment import EvidenceAssessment
    from app.services import grounding, main_context
    from app.services.run_metrics import RunMetrics
    from app.clients.mysql_client import db

    state = seeded_state(case)
    blocked_calls = []
    candidate = {}

    def deny(name):
        async def blocked(*args, **kwargs):
            blocked_calls.append(name)
            raise RuntimeError('Synthetic synthesis evaluation prohibits storage and external action execution')
        return blocked

    async def capture_main(current):
        update = await main_agent.main_agent_node(current)
        candidate.update(reply=update.get('final_reply', ''), main_decision=update.get('main_decision', {}))
        return update

    graph = StateGraph(AgentState)
    graph.add_node('main_agent', capture_main)
    graph.add_node('final_gate', staged_runtime.final_gate)
    graph.add_edge(START, 'main_agent')
    # Non-answer decisions are recorded as failures, never dispatched to tools.
    graph.add_conditional_edges('main_agent', lambda current: 'final_gate'
        if current.get('main_action') == 'answer' and not current.get('stop_reason') else END,
        {'final_gate': 'final_gate', END: END})
    graph.add_edge('final_gate', END)
    compiled = graph.compile()
    metrics = RunMetrics()
    control = None

    async def replay_review(text, sources, facts):
        blocks = grounding.text_blocks(text)
        units = grounding.review_units(blocks)
        contents = {str(source['id']): source['content'] for source in sources}
        reviews = []
        for index, block in enumerate(blocks):
            claims = []
            for unit in units[index]:
                refs = [ref for ref in unit['citation_ids'] if ref in contents]
                label = unit.get('citation_role') == 'label' or unit['text'].startswith('#')
                kind = 'non_factual' if label else 'inference' if refs else 'general_knowledge'
                claims.append(grounding.ClaimReview(unit_index=unit['unit_index'], statement=unit['text'], kind=kind,
                    verdict='non_factual' if label else 'supported', reason='脚本回放标签，不是独立语义事实判断',
                    rationale='固定合成示例的预设解释或条件性推理，仅验证执行契约',
                    quotes=[grounding.Quote(citation_id=ref, text=contents[ref]) for ref in refs]))
            reviews.append(grounding.BlockReview(block_index=index, claims=claims))
        return grounding.validate_review(grounding.GroundingReview(blocks=reviews), blocks, sources, facts=facts)

    with ExitStack() as stack:
        # This evaluator has no retrieval dispatcher; do not terminate with a
        # pending lookup and mistake an unreviewed candidate for final output.
        stack.enter_context(patch('app.graph.delivery_recovery.can_lookup', return_value=False))
        # Live calls may only reach the configured LLM. Database and memory
        # methods remain hard-blocked even if Main unexpectedly emits a change.
        for name in ('connect', 'disconnect', 'fetch_all', 'fetch_one', 'fetch_val', 'execute', 'execute_many'):
            stack.enter_context(patch.object(db, name, side_effect=deny(f'db.{name}')))
        stack.enter_context(patch.object(main_agent.memory_policy_service, 'enqueue_changes', side_effect=deny('memory.enqueue_changes')))
        stack.enter_context(patch.object(main_context.context_service, 'compact_history', side_effect=deny('history.compact_history')))
        if mode == 'replay':
            assessment = EvidenceAssessment(selected_ids=[citation['id'] for citation in state['task_results']['retrieve_1']['citations']],
                adequacy=case.get('adequacy', 'sufficient'), reason='固定合成资料；回放标签不评价真实模型质量',
                missing_aspects=case.get('missing_aspects', []))
            decision = main_agent.MainDecision(action='answer', reply=case['reply'], answer_dependencies=['retrieve_1'],
                evidence_assessment=assessment)
            control = SimpleNamespace(ainvoke=AsyncMock(return_value=decision))
            model = SimpleNamespace(with_structured_output=Mock(return_value=control))
            stack.enter_context(patch.object(main_agent, 'get_llm', return_value=model))
            stack.enter_context(patch.object(grounding, 'review_text', side_effect=replay_review))
            stack.enter_context(patch.object(grounding, 'repair_text', side_effect=deny('unexpected_replay_repair')))
        result = await compiled.ainvoke(state, config={'callbacks': [metrics]})
    assertions = assertions_for(case, result, blocked_calls)
    return {'id': case['id'], 'category': case['category'], 'scope': SCOPE,
        'candidate_reply': candidate.get('reply', ''), 'reply': result.get('final_reply', ''),
        'main_decision': result.get('main_decision') or {}, 'audit': result.get('grounding_audit') or {},
        'assertions': assertions, 'assertions_passed': all(assertions.values()), 'blocked_calls': blocked_calls,
        'scripted_main_calls': control.ainvoke.await_count if control else None, 'metrics': metrics.snapshot()}


async def run(args):
    selected = [case for case in cases() if not args.ids or case['id'] in args.ids]
    if args.ids and set(args.ids) - {case['id'] for case in selected}:
        raise ValueError('未知样例ID')
    if args.limit:
        selected = selected[:args.limit]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'mode': args.mode, 'scope': SCOPE, 'synthetic_cases': len(selected),
        'live_models': ['main_decision', 'delivery_auditor', 'delivery_repairer_if_required'] if args.mode == 'live' else [],
        'source_sha256': hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'state': {'run_id': '', 'articleId': '', 'history_messages': [], 'retrieval': 'seeded_fixture_only'},
        'latency_scope': 'seeded_main_decision_and_delivery; excludes_actual_retrieval; first_case_includes_cold_imports',
        'note': NOTE}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    with (output / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
        for case in selected:
            started = time.perf_counter()
            try:
                row = await asyncio.wait_for(execute(case, args.mode), args.timeout)
            except Exception as exc:
                # Avoid printing provider errors, credentials or arbitrary payloads.
                row = {'id': case['id'], 'category': case['category'], 'scope': SCOPE,
                    'assertions_passed': False, 'error_type': type(exc).__name__}
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            print(f'{case["id"]}: {"smoke_pass" if row["assertions_passed"] else "smoke_fail"}', flush=True)
    summary = {'mode': args.mode, 'scope': SCOPE, 'cases': len(rows),
        'smoke_assertions_passed': sum(row['assertions_passed'] for row in rows),
        'errors': sum('error_type' in row for row in rows),
        'p50_ms': percentile([row['latency_ms'] for row in rows], 50),
        'p95_ms': percentile([row['latency_ms'] for row in rows], 95),
        'human_synthesis_quality': None, 'note': NOTE}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    by_id = {row['id']: row for row in rows}
    reviews = [{'id': case['id'], 'query': case['query'], 'sources': case['sources'],
        'candidate_reply': by_id[case['id']].get('candidate_reply'), 'final_reply': by_id[case['id']].get('reply'),
        'review_question': case['human_review'], 'human_pass': None, 'reviewer': None} for case in selected]
    (output / 'reviews.template.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in reviews), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['smoke_assertions_passed'] == len(rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['replay', 'live'], default='replay')
    parser.add_argument('--output', required=True)
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--timeout', type=int, default=150)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1 or args.timeout < 1:
        parser.error('limit和timeout必须为正数')
    os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
    if args.mode == 'replay':
        os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-replay')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
