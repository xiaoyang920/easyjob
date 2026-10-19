"""Bounded Main-only replay of public retrieval artifacts; no business writes.

Requires --live and a reviewed frozen public-source plan. Excludes conversation history,
profile, constraints, private memories, attachments and draft artifacts.
Never logs the raw model answer, evidence bodies or provider error text.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

from app.graph import main_agent as agent
from app.graph.state_factory import create_initial_state
from app.config import get_llm, settings
from pydantic import ValidationError


def diagnostic(response):
    error = response.get('parsing_error') if isinstance(response, dict) else None
    raw = response.get('raw') if isinstance(response, dict) else None
    calls = getattr(raw, 'tool_calls', []) or []
    args = calls[0].get('args', {}) if len(calls) == 1 else {}
    assessment = args.get('evidence_assessment') if isinstance(args, dict) else None
    report = {'action': args.get('action'), 'schema_valid': error is None,
              'issues': error.errors(include_input=False, include_url=False, include_context=False)
                        if isinstance(error, ValidationError) else [{'type': type(error).__name__}] if error else []}
    if isinstance(assessment, dict):
        report['assessment'] = {key: assessment.get(key) for key in ('adequacy', 'selected_ids')}
        report['assessment'].update(selected_ids_present='selected_ids' in assessment,
                                    missing_count=len(assessment.get('missing_aspects') or []),
                                    conflict_count=len(assessment.get('conflicts') or []))
    return report


async def main(plan_path, phase):
    report = {'phase': phase, 'scope': 'approved question and four university public sources; one call this phase', 'calls': []}
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        citations = plan['citations']
        if len(citations) != 4 or any(not (urlsplit(c.get('url', '')).hostname or '').endswith('.qlu.edu.cn') for c in citations):
            raise ValueError('Replay must use only the four approved university sources')
        if urlsplit(settings.DEEPSEEK_BASE_URL).hostname != 'api.deepseek.com':
            raise ValueError('Replay provider does not match DeepSeek')
        state = create_initial_state(0, plan['question'], [])
        contents = plan['citation_contents']
        state.update(main_round=1, main_action='retrieve', task_results={'retrieve_1': {
            'task_id': 'retrieve_1', 'actor': 'main', 'kind': 'search', 'retrieval_target': 'knowledge',
            'status': 'succeeded', 'instruction': plan['question'], 'citations': citations,
            'citation_contents': contents, 'article_cards': [],
            'result': '\n\n'.join(f"[{c['id']}] {contents[str(c['id'])]}" for c in citations),
            'retrieval_report': {'assessment_owner': 'main', 'web': {'status': 'found', 'candidates': 4}}}})
        base = get_llm(temperature=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS, max_retries=0)
        control = base.with_structured_output(agent.MainDecision, method='function_calling', include_raw=True)
        messages = agent.build_main_messages(state)
        budget_path = ROOT / 'logs/evidence-assessment-approved-budget.json'
        budget = json.loads(budget_path.read_text()) if budget_path.exists() else {'calls_reserved': []}
        if len(budget['calls_reserved']) >= 2:
            raise RuntimeError('Approved total model-call budget exhausted')
        budget['calls_reserved'].append({'phase': phase, 'at': datetime.now(timezone.utc).isoformat()})
        budget_path.write_text(json.dumps(budget, indent=2), encoding='utf-8')
        response = await asyncio.wait_for(control.ainvoke(messages), 70)
        report['calls'].append(diagnostic(response))
        decision = agent.parse_decision(response, agent.MainDecision)
        agent.validate_evidence_assessment(state, decision)
        agent.preflight_action(state, decision, 2)
        report['action'] = decision.action
        report['checks'] = {'valid_next_action': True, 'no_business_mutations': True,
                            'bounded_model_calls': len(budget['calls_reserved']) <= 2}
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    finally:
        destination = ROOT / f'logs/evidence-assessment-{phase}.json'
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    return all(report.get('checks', {}).values()) and bool(report.get('checks'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'logs/evidence-assessment-live-plan.json')
    parser.add_argument('--phase', choices=['before', 'after'], required=True)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(main(args.plan, args.phase)) else 1)
