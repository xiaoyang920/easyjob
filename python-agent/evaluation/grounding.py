"""Production graph replay, or live audit of fixed synthetic candidate answers.

No database writes, saved drafts or real web searches. Live mode calls the
configured provider only for the new delivery auditor/repairer, not Main.
"""
import argparse
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from evaluation.grounding_cases import cases
from evaluation.metrics import percentile


def unqualified_claim_present(text, phrase):
    """Narrow smoke check: negating a bad claim is not adopting that claim.

    This is a clause-level heuristic, not semantic truth evaluation. Human
    review still owns correctness and all ambiguous cases.
    """
    boundary = r'[，,。！？；;.!?\n]'
    for match in re.finditer(re.escape(phrase), text):
        prefix = re.split(boundary, text[:match.start()])[-1][-40:]
        suffix = re.split(boundary, text[match.end():])[0][:40]
        if re.search(r'(?:不能|无法|不足以|不代表|并非|没有依据|不能据此).{0,20}$', prefix):
            continue
        if re.match(r'[^，,。！？；;.!?\n]{0,12}(?:是错误的|不成立|缺乏依据|没有依据|不能确认)', suffix):
            continue
        return True
    return False


async def execute(case, mode):
    from app.graph import builder, main_agent, action_runtime
    from app.graph.state_factory import create_initial_state
    from app.models.evidence_assessment import EvidenceAssessment
    from app.services import grounding
    from app.services.run_metrics import RunMetrics
    cid = 'retrieve_1:1'
    citation = {'id': cid, 'articleId': '', 'title': case['id'], 'excerpt': case['source'],
                'contentScope': case.get('content_scope', 'fixture_text')}
    citations = [citation]
    contents = {cid: case['source']}
    if case.get('extra_source'):
        citations.append({**citation, 'id': 'retrieve_1:2', 'excerpt': case['extra_source']})
        contents['retrieve_1:2'] = case['extra_source']
    adequacy = case.get('adequacy', 'sufficient')
    assessment = EvidenceAssessment(selected_ids=[] if adequacy == 'none' else list(contents), adequacy=adequacy,
        reason='固定合成资料', missing_aspects=['实现细节'] if adequacy == 'partial' else [],
        conflicts=[{'citation_ids': list(contents), 'description': '不同版本默认值不同'}] if case.get('conflict') else [])
    decisions = [main_agent.MainDecision(action='retrieve', retrieval=main_agent.RetrievalRequest(
        instruction=case['query'], filters={}, allow_web=case['web'] != 'not_requested')),
        main_agent.MainDecision(action='answer', reply=case['candidate'], evidence_assessment=assessment)]
    main_control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
    main_model = SimpleNamespace(with_structured_output=Mock(return_value=main_control))
    evidence = {'status': 'succeeded', 'rag_context': '\n\n'.join(f'[{key}] {content}' for key, content in contents.items()), 'citations': citations,
        'citation_contents': contents, 'article_cards': [],
        'retrieval_report': {'assessment_owner': 'main', 'platform': {'status': 'found'}, 'web': {'status': case['web']}}}
    graph = builder._build_graph().compile()
    metrics = RunMetrics()
    async def replay_review(text, sources, facts):
        if case.get('simulate_timeout'):
            raise TimeoutError('scripted auditor timeout')
        if case.get('simulate_invalid_response'):
            raise ValueError('scripted invalid auditor coverage')
        first = text == case['candidate']
        quote = case.get('scripted_quote', case['source']) if first else case['source']
        verdict = case.get('scripted_verdict', 'supported') if first else 'supported'
        quotes = [grounding.Quote(citation_id=case.get('audit_citation_id', cid) if first else cid, text=quote)] if quote else []
        if case.get('extra_source'):
            quotes.append(grounding.Quote(citation_id='retrieve_1:2', text=case['extra_source']))
        blocks = grounding.text_blocks(text)
        document_units = grounding.review_units(blocks)
        reviews = []
        for i, block in enumerate(blocks):
            claims = []
            for unit in document_units[i]:
                spec = case.get('scripted_units', {}).get(unit['text'], {})
                unit_quotes = quotes
                if case.get('extra_source') and len(unit['citation_ids']) == 1 and (not first or not case.get('audit_citation_id')):
                    ref = unit['citation_ids'][0]
                    unit_quotes = [grounding.Quote(citation_id=ref, text=contents[ref])]
                kind = spec.get('kind', case.get('scripted_kind' if first else 'repair_kind', 'source_fact'))
                structural = case.get('scripted_scope_labels') and (unit.get('citation_role') == 'label'
                    or unit['text'].startswith(('## ', '| Option', '| ---')))
                if structural:
                    kind = 'non_factual'
                if spec.get('no_quotes') or kind in ('recommendation', 'general_knowledge', 'illustration', 'non_factual'):
                    unit_quotes = []
                claims.append(grounding.ClaimReview(unit_index=unit['unit_index'], statement=unit['text'], kind=kind,
                    issue_code=spec.get('issue_code', 'none'),
                    missing_information=spec.get('missing_information', 'none'),
                    rationale=spec.get('rationale', case.get('rationale', '')),
                    verdict='non_factual' if structural else spec.get('verdict', verdict if first else case.get('repair_verdict', verdict)),
                    reason='脚本回放标签，不是模型质量判断', quotes=unit_quotes))
            reviews.append(grounding.BlockReview(block_index=i, claims=claims))
        return grounding.validate_review(grounding.GroundingReview(blocks=reviews), blocks, sources)
    with patch.object(main_agent, 'get_llm', return_value=main_model), \
         patch.object(action_runtime, 'retrieve_evidence', AsyncMock(return_value=evidence)), \
         patch('app.graph.delivery_recovery.can_lookup', return_value=False):
        # This benchmark isolates a fixed candidate's audit/repair quality;
        # dynamic lookup is measured by test_delivery_recovery, not replayed here.
        if mode == 'replay':
            with patch.object(grounding, 'review_text', side_effect=replay_review), \
                 patch.object(grounding, 'repair_text', AsyncMock(return_value=case.get('repair', case['candidate']),
                     side_effect=TimeoutError('scripted repair timeout') if case.get('repair_timeout') else None)):
                result = await graph.ainvoke(create_initial_state(7, case['query'], []), config={'callbacks': [metrics]})
        else:
            result = await graph.ainvoke(create_initial_state(7, case['query'], []), config={'callbacks': [metrics]})
    audit = result['grounding_audit']
    reply = result['final_reply']
    assertions = {'forbidden_absent': all(text not in reply for text in case.get('forbidden', [])),
                  'required_present': all(text in reply for text in case.get('required', []))}
    if case.get('forbidden_claims'):
        assertions['unqualified_claims_absent'] = all(not unqualified_claim_present(reply, phrase)
            for phrase in case['forbidden_claims'])
    if mode == 'replay':
        assertions['expected_status'] = audit['status'] == case['expected']
    else:
        assertions['supported_answer_not_refused'] = case['category'] not in (
            'supported', 'source_injection', 'mixed_recommendation', 'reasoning', 'general_knowledge', 'illustration', 'conditional_advice', 'long_markdown', 'citation_scope'
        ) or audit['status'] in ('verified', 'repaired')
    return {'id': case['id'], 'category': case['category'], 'reply': reply, 'audit': audit,
            'assertions': assertions, 'assertions_passed': all(assertions.values()),
            'scripted_main_calls': main_control.ainvoke.await_count, 'metrics': metrics.snapshot()}


async def run(args):
    selected = [case for case in cases() if (not args.ids or case['id'] in args.ids)
        and (args.mode == 'replay' or case['category'] not in ('missing_quote', 'auditor_failure'))]
    if args.ids and set(args.ids) - {case['id'] for case in selected}:
        raise ValueError('未知样例ID，或选择了仅支持回放的故障注入样例')
    selected = selected[:args.limit] if args.limit else selected
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'mode': args.mode, 'scope': 'production_graph_with_scripted_main_and_recorded_retrieval',
        'live_models': ['delivery_auditor', 'delivery_repairer'] if args.mode == 'live' else [],
        'synthetic_cases': len(selected), 'source_sha256': hashlib.sha256(json.dumps(selected, ensure_ascii=False).encode()).hexdigest(),
        'latency_scope': 'graph_and_delivery; first_case_includes_cold_python_imports',
        'note': '回放通过率不是模型准确率；真实核验结果也不作为独立事实标注。需人工复核。'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    with (output / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
        for case in selected:
            started = time.perf_counter()
            try:
                row = await asyncio.wait_for(execute(case, args.mode), args.timeout)
            except Exception as exc:
                row = {'id': case['id'], 'category': case['category'], 'assertions_passed': False,
                       'error_type': type(exc).__name__}
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            print(f'{case["id"]}: {row.get("audit", {}).get("status", row.get("error_type"))}', flush=True)
    summary = {'mode': args.mode, 'cases': len(rows), 'assertions_passed': sum(row['assertions_passed'] for row in rows),
        'errors': sum('error_type' in row for row in rows),
        'audit_unverified': sum(row.get('audit', {}).get('status') == 'unverified' for row in rows),
        'audit_counts': {status: sum(row.get('audit', {}).get('status') == status for row in rows)
                         for status in sorted({row.get('audit', {}).get('status', 'error') for row in rows})},
        'p50_ms': percentile([row['latency_ms'] for row in rows], 50),
        'p95_ms': percentile([row['latency_ms'] for row in rows], 95),
        'human_supported_claim_rate': None,
        'note': manifest['note']}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    reviews = [{'id': case['id'], 'source': case['source'], 'candidate': case['candidate'],
        'extra_source': case.get('extra_source'),
        'final_reply': next(row.get('reply') for row in rows if row['id'] == case['id']),
        'total_claims': None, 'supported_claims': None, 'false_refusal': None, 'reviewer': None} for case in selected]
    (output / 'reviews.template.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in reviews), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['assertions_passed'] == len(rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['replay', 'live'], default='replay')
    parser.add_argument('--output', required=True)
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--timeout', type=int, default=100)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1 or args.timeout < 1:
        parser.error('limit和timeout必须为正数')
    import os
    os.environ.setdefault('LANGFUSE_TRACING_ENABLED', 'false')
    if args.mode == 'replay':
        os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-replay')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
