"""Opt-in read-only replay of the Main decision after an existing retrieval.

Uses the configured provider and recorded context. Does not rerun searches,
resume the old executor, write chat history or perform business mutations.
Only diagnostic codes and booleans are saved, never model text or source bodies.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.graph.builder import get_graph, close_graph
from app.graph import main_agent as agent
from app.services.grounding import verify_delivery
from app.config import get_llm, settings
from pydantic import ValidationError


async def main(run_id, inject):
    report = {'source_run_id': run_id, 'injected_invalid_first_decision': inject, 'checks': {}}
    try:
        graph = await get_graph()
        state = None
        async for snapshot in graph.aget_state_history({'configurable': {'thread_id': f'run_{run_id}'}}):
            if snapshot.next == ('main_agent',) and snapshot.values.get('task_results'):
                state = dict(snapshot.values)
                break
        assert state is not None, 'No completed-retrieval checkpoint before Main'
        state.update(run_id='', execution_token='', conversation_id=None)
        state['decision_contract_audit'] = {}
        base = get_llm(temperature=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS)
        real_control = base.with_structured_output(agent.MainDecision, method='function_calling', include_raw=True)
        injected = False
        async def invoke(messages, **kwargs):
            nonlocal injected
            if inject and not injected:
                injected = True
                args = {'action': 'answer', 'reply': '不能确认出处。', 'evidence_assessment': {
                    'selected_ids': [], 'adequacy': 'partial', 'reason': '尚缺出处证据', 'missing_aspects': ['原始出处']}}
                try:
                    agent.MainDecision.model_validate(args)
                except ValidationError as exc:
                    return {'raw': SimpleNamespace(tool_calls=[{'name': 'MainDecision', 'args': args}]),
                            'parsed': None, 'parsing_error': exc}
            return await real_control.ainvoke(messages, **kwargs)
        facade = SimpleNamespace(with_structured_output=lambda schema, **kw:
            SimpleNamespace(ainvoke=invoke) if schema is agent.MainDecision else base.with_structured_output(schema, **kw))
        no_write = AsyncMock(side_effect=AssertionError('Read-only replay must not enqueue business mutations'))
        with patch.object(agent, 'get_llm', return_value=facade), \
             patch.object(agent.memory_policy_service, 'enqueue_changes', no_write):
            update = await agent.decide_main_action(state)
        no_write.assert_not_awaited()
        report['checks']['no_business_mutations'] = True
        report['action'] = update['main_action']
        report['decision_contract_audit'] = update.get('decision_contract_audit', {})
        assert update['main_action'] == 'answer' and not update.get('stop_reason'), 'Main failed to deliver a valid answer'
        assessment = update['main_decision'].get('evidence_assessment') or {}
        report['adequacy'] = assessment.get('adequacy')
        assert assessment.get('adequacy') == 'none' and not assessment.get('selected_ids'), 'Unrelated results must not be treated as confirmed provenance'
        report['checks']['irrelevant_results_accepted_as_valid_none'] = True
        merged = {**state, **update}
        _, audit = await verify_delivery(merged, update['final_reply'],
            update.get('delivery_evidence', {}).get('citations', []), allow_retrieval=False)
        report['grounding_status'] = audit['status']
        assert audit['status'] in ('verified', 'repaired'), 'Unconfirmed-source answer did not pass final review'
        report['checks']['answer_passes_independent_grounding'] = True
        if inject:
            assert update.get('decision_contract_audit', {}).get('last_outcome') == 'repaired', 'Injected error was not repaired'
            report['checks']['bounded_format_repair_uses_real_model'] = True
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        if isinstance(exc, AssertionError):
            report['error'] = str(exc)
    finally:
        await close_graph()
        name = 'decision-contract-replay-repair.json' if inject else 'decision-contract-replay.json'
        (ROOT / 'logs' / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--inject-invalid-first', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required')
    raise SystemExit(0 if asyncio.run(main(args.run_id, args.inject_invalid_first)) else 1)
