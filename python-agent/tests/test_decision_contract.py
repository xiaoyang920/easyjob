"""Production Main repair: bad fields, rejected controls, irrelevant hits and cancellation."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from app.graph import main_agent as agent
from app.graph.state_factory import create_initial_state
from app.services.decision_contract import parse_decision, contract_issues, rejected_controls
from app.services.run_history import progress_snapshot


def envelope(args, parsed=None, error=None, calls=None):
    return {'raw': SimpleNamespace(tool_calls=calls if calls is not None else [
        {'name': 'MainDecision', 'args': args, 'id': 'decision-call'}]),
        'parsed': parsed, 'parsing_error': error}


def none_answer():
    return agent.MainDecision(action='answer', reply='已检索，但返回资料无法确认作品出处；可以补充原始链接。',
        answer_dependencies=['lookup'], evidence_assessment=agent.EvidenceAssessment(
            selected_ids=[], adequacy='none', reason='资料不能确认出处', missing_aspects=['原始发布链接']))


class DecisionContractTests(unittest.IsolatedAsyncioTestCase):
    def state(self):
        state = create_initial_state(7, '这张图来自哪部作品', [])
        state['main_round'] = 1
        state['task_results'] = {'lookup': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
            'retrieval_target': 'knowledge', 'result': '无关的插画教程',
            'citations': [{'id': 'lookup:web1', 'title': '泛泛的插画教程', 'url': 'https://example.org/', 'articleId': ''}],
            'retrieval_report': {'assessment_owner': 'main', 'platform': {'status': 'empty'},
                                 'web': {'status': 'found', 'provider': 'deepseek', 'candidates': 1}}}}
        return state

    async def decide(self, responses, state=None):
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        with patch.object(agent, 'get_llm', return_value=model):
            result = await agent.decide_main_action(state or self.state())
        return result, control

    async def test_semantic_repair_receives_exact_error_and_allowed_citation_ids(self):
        bad = none_answer().model_copy(deep=True)
        bad.evidence_assessment = agent.EvidenceAssessment(selected_ids=['unknown:web1'], adequacy='partial', reason='待确认')
        good = none_answer()
        result, control = await self.decide([envelope(bad.model_dump(), bad), envelope(good.model_dump(), good)])
        prompt = control.ainvoke.await_args_list[1].args[0][-1].content
        self.assertIn('资料评估只能选择成功依赖中的原始引用id', prompt)
        self.assertIn('lookup:web1', prompt)
        self.assertIn('unknown:web1', prompt)  # rejected controls, clearly separated from allowed IDs
        self.assertIn('不能混用两类编号', prompt)
        self.assertEqual(result['final_reply'], good.reply)
        self.assertIsNone(result['citations'])
        self.assertEqual(result['decision_contract_audit']['failures'][-1]['stage'], 'evidence_assessment')

    async def test_nested_schema_error_is_repaired_without_relaxing_selection_rules(self):
        bad = none_answer().model_dump()
        bad['evidence_assessment']['adequacy'] = 'partial'
        with self.assertRaises(ValidationError) as caught:
            agent.MainDecision.model_validate(bad)
        good = none_answer()
        result, control = await self.decide([envelope(bad, error=caught.exception), envelope(good.model_dump(), good)])
        prompt = control.ainvoke.await_args_list[1].args[0][-1].content
        self.assertIn('evidence_assessment', prompt)
        self.assertIn('资料充分性与选择结果不一致', prompt)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result['main_decision']['evidence_assessment']['adequacy'], 'none')
        self.assertFalse(result['main_decision']['evidence_assessment']['selected_ids'])

    async def test_irrelevant_hits_are_valid_none_result_without_format_repair(self):
        good = none_answer()
        result, control = await self.decide([envelope(good.model_dump(), good)])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual(result['main_action'], 'answer')
        self.assertEqual(result['stop_reason'], '')
        self.assertIsNone(result['citations'])
        self.assertEqual(result['delivery_evidence']['citations'], [])

    async def test_parser_failure_does_not_echo_raw_model_text_or_secret_to_repair_or_audit(self):
        secret = 'private-reply-secret'
        error = OutputParserException('provider returned ' + secret, llm_output=secret)
        bad = {'action': 'answer', 'user_reply': secret}
        good = none_answer()
        result, control = await self.decide([envelope(bad, error=error), envelope(good.model_dump(), good)])
        repair = control.ainvoke.await_args_list[1].args[0][-1].content
        self.assertNotIn(secret, repair)
        self.assertNotIn(secret, json.dumps(result['decision_contract_audit']))
        snapshot = progress_snapshot({**self.state(), **result}, 'main_agent', 'succeeded')
        self.assertEqual(snapshot['decision_contract_audit']['last_outcome'], 'repaired')

    async def test_two_bad_outputs_stop_with_known_retrieval_status_and_keep_sources(self):
        bad = envelope({}, error=OutputParserException('private provider output'))
        state = self.state()
        result, control = await self.decide([bad, bad], state)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertIn('检索已返回候选资料', result['final_reply'])
        self.assertNotIn('动作格式', result['final_reply'])
        self.assertNotIn('private', result['final_reply'])
        self.assertEqual(result['backend_boundary']['reason_code'], 'decision_after_retrieval')
        self.assertEqual(state['task_results']['lookup']['status'], 'succeeded')
        self.assertEqual(len(result['decision_contract_audit']['failures']), 2)
        merged = {**state, **result}
        self.assertTrue(agent.valid_backend_boundary(merged, result['final_reply'], []))
        self.assertFalse(agent.valid_backend_boundary({**merged, 'task_results': {}}, result['final_reply'], []))

    async def test_no_retrieval_does_not_claim_search_was_completed(self):
        bad = envelope({}, error=OutputParserException('invalid'))
        result, _ = await self.decide([bad, bad], create_initial_state(7, 'hello', []))
        self.assertNotIn('检索已返回', result['final_reply'])
        self.assertEqual(result['backend_boundary']['reason_code'], 'action_contract')

    async def test_cancelled_generation_is_not_converted_to_a_format_error(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.decide([asyncio.CancelledError()])

    def test_multiple_or_wrong_function_calls_are_rejected(self):
        good = none_answer()
        for calls in [[], [{'name': 'save_article', 'args': {}}],
                      [{'name': 'MainDecision', 'args': {}}, {'name': 'MainDecision', 'args': {}}]]:
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                parse_decision(envelope({}, parsed=good, calls=calls), agent.MainDecision)

    def test_rejected_controls_omit_prose_and_remain_bounded(self):
        candidate = {'action': 'delegate', 'user_reply': 'private', 'artifacts': [
            {'task_id': 'notes', 'result': 'private body', 'instruction': 'x' * 100000, 'depends_on': ['lookup']}]}
        controls = rejected_controls(candidate)
        self.assertNotIn('private', json.dumps(controls))
        self.assertLess(len(json.dumps(controls)), 16000)
        self.assertEqual(controls['artifacts'][0]['depends_on'], ['lookup'])


if __name__ == '__main__':
    unittest.main()
