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
from app.services.decision_contract import parse_decision, contract_issues, rejected_controls, rejection_snapshot
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
    def test_optional_lists_stay_strict_and_do_not_normalize_null(self):
        for field in ('artifacts', 'answer_dependencies', 'reuse_previous_results', 'memory_changes', 'constraint_overrides'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                agent.MainDecision.model_validate({'action': 'retrieve', 'retrieval': {'instruction': '查证'}, field: None})

    async def test_real_live_failure_pattern_is_rejected_and_exact_control_relation_is_retained(self):
        # Actual disputed controls from the approved three-call diagnosis.
        state = self.state()
        tid = 'retrieve_quanzhi_latest'
        state['task_results'] = {tid: state['task_results']['lookup']}
        first = {'action': 'write_draft', 'artifacts': None, 'reuse_previous_results': [tid],
            'draft_request': {'task_id': 'draft_intro', 'instruction': '写介绍', 'depends_on': [tid], 'requires_evidence': True},
            'evidence_assessment': {'selected_ids': ['lookup:web1'], 'adequacy': 'sufficient', 'reason': '冻结资料'}}
        with self.assertRaises(ValidationError) as caught:
            agent.MainDecision.model_validate(first)
        second = agent.MainDecision(action='retrieve', artifacts=[], reuse_previous_results=[tid],
            retrieval=agent.RetrievalRequest(instruction='继续检索'),
            evidence_assessment=agent.EvidenceAssessment(selected_ids=['lookup:web1'], adequacy='sufficient', reason='冻结资料'))
        result, control = await self.decide([envelope(first, error=caught.exception), envelope(second.model_dump(), second)], state)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result['decision_contract_audit']['last_outcome'], 'stopped')
        first_audit, second_audit = result['decision_contract_audit']['failures']
        self.assertEqual(first_audit['controls']['artifacts'], {'present': True, 'type': 'NoneType', 'value': None})
        self.assertEqual(second_audit['controls']['reuse_previous_results']['references'],
            [{'id': tid, 'relation': 'current_successful_task'}])
        self.assertEqual(second_audit['controls']['reuse_previous_results']['allowed_previous_ids'], [])
        self.assertEqual(second_audit['diagnostics']['current_results_misfiled_count'], 1)

    async def test_observed_two_error_categories_recover_into_writing_in_two_calls(self):
        # The production log retained list_type, not its rejected raw value.
        # Use an explicitly invalid scalar fixture; do not claim it was null.
        bad = {'action': 'retrieve', 'retrieval': {'instruction': '补资料'}, 'artifacts': 17}
        with self.assertRaises(ValidationError) as caught:
            agent.MainDecision.model_validate(bad)
        good = agent.MainDecision(action='write_draft', reuse_previous_results=[],
            evidence_assessment=agent.EvidenceAssessment(selected_ids=['lookup:web1'], adequacy='sufficient', reason='冻结资料'),
            draft_request={'task_id': 'draft_intro', 'instruction': '写介绍', 'depends_on': ['lookup'], 'requires_evidence': True})
        result, control = await self.decide([envelope(bad, error=caught.exception), envelope(good.model_dump(), good)])
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result['main_action'], 'write_draft')
        self.assertEqual(result['decision_contract_audit']['last_outcome'], 'repaired')
        self.assertEqual(result['decision_contract_audit']['failures'][0]['issues'][0],
                         {'path': 'artifacts', 'type': 'list_type', 'input_type': 'int'})
        repair = control.ainvoke.await_args_list[1].args[0][-1].content
        self.assertIn('reuse_previous_results只能选reusable_previous_task_ids', repair)

    def test_single_artifact_requires_a_list_and_invalid_values_are_not_discarded(self):
        artifact = {'task_id': 'notes', 'instruction': '观察', 'result': '保留这段完整观察'}
        parsed = agent.MainDecision.model_validate({'action': 'retrieve', 'retrieval': {'instruction': '查证'}, 'artifacts': [artifact]})
        self.assertEqual(parsed.artifacts[0].result, artifact['result'])
        for invalid in ('not a list', False, {}, artifact, [{'task_id': 'notes', 'result': '缺少必填字段'}]):
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                agent.MainDecision.model_validate({'action': 'retrieve', 'retrieval': {'instruction': '查证'}, 'artifacts': invalid})

    def test_reuse_cannot_import_unknown_failed_duplicate_or_conflicting_results(self):
        state = self.state()
        state['task_results']['failed'] = {'status': 'tool_error'}
        for selected in (['unknown'], ['lookup:web1'], ['failed'], ['lookup'], ['lookup', 'lookup']):
            with self.subTest(selected=selected), self.assertRaises(agent.ReuseContractError):
                agent.previous_results_to_import(state, selected)
        state['previous_run'] = {'reusable_results': {'lookup': {'status': 'succeeded', 'result': 'different'}}}
        with self.assertRaises(agent.ReuseContractError) as raised:
            agent.previous_results_to_import(state, ['lookup'])
        self.assertEqual(raised.exception.diagnostics['collision_count'], 1)

    def test_mixed_current_and_verified_previous_results_only_import_missing_history(self):
        state = self.state()
        old = {'task_id': 'previous_1_lookup', 'status': 'succeeded', 'result': 'verified'}
        state['previous_run'] = {'reusable_results': {old['task_id']: old}}
        self.assertEqual(agent.previous_results_to_import(state, [old['task_id']]), {old['task_id']: old})
        with self.assertRaises(agent.ReuseContractError):
            agent.previous_results_to_import(state, ['lookup', old['task_id']])

    async def test_strict_valid_writing_reaches_actual_approval_node(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from app.graph import builder
        from app.graph.nodes import writing_worker
        from app.models.draft import DraftOutput
        state = self.state()
        wire = {'action': 'write_draft', 'artifacts': [], 'reuse_previous_results': [],
            'draft_request': {'task_id': 'draft_intro', 'instruction': '根据资料写介绍',
                'depends_on': ['lookup'], 'requires_evidence': True},
            'evidence_assessment': {'selected_ids': ['lookup:web1'], 'adequacy': 'sufficient', 'reason': '冻结资料'}}
        control = SimpleNamespace(ainvoke=AsyncMock(return_value=envelope(wire, agent.MainDecision.model_validate(wire))))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        graph = builder._build_graph().compile(checkpointer=InMemorySaver())
        config = {'configurable': {'thread_id': self.id()}}
        with patch.object(agent, 'get_llm', return_value=model), \
             patch.object(writing_worker, 'generate_draft', AsyncMock(return_value=DraftOutput(
                 title='介绍', summary='', content='冻结资料正文。[lookup:web1]'))) as generate, \
             patch('app.services.grounding.review_text', AsyncMock(return_value=[])), \
             patch('app.services.evidence_verifier.verify_public_evidence', AsyncMock()), \
             patch.object(writing_worker, 'save_approved_draft', AsyncMock()) as save:
            await graph.ainvoke(state, config)
            snapshot = await graph.aget_state(config)
        self.assertEqual(snapshot.tasks[0].interrupts[0].value['action'], 'confirm_save_draft')
        self.assertEqual(control.ainvoke.await_count, 1)
        generate.assert_awaited_once()
        save.assert_not_awaited()

    def test_diagnostics_distinguish_citation_and_current_task_without_saving_unknown_text(self):
        private = 'private text must never be persisted'
        response = envelope({'user_reply': private, 'reuse_previous_results': ['lookup', 'lookup:web1', private]})
        snapshot = rejection_snapshot(self.state(), response, [{'path': 'reuse_previous_results'}])
        refs = snapshot['reuse_previous_results']['references']
        self.assertEqual([r['relation'] for r in refs], ['current_successful_task', 'citation_not_task', 'unknown'])
        self.assertNotIn(private, json.dumps(snapshot))
        self.assertEqual(len(refs[-1]['hash']), 64)

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

    def test_wire_schema_requires_selection_and_documents_cross_field_rules(self):
        schema = agent.MainDecision.model_json_schema()['$defs']['EvidenceAssessment']
        self.assertIn('selected_ids', schema['required'])
        self.assertIn('write_draft', schema['properties']['selected_ids']['description'])
        self.assertIn('conflicts=[]', schema['properties']['adequacy']['description'])

    async def test_observed_missing_selection_is_repaired_into_targeted_retrieval(self):
        state = self.state()
        state['user_message'] = '帮我写一篇学校介绍文章'
        state['task_results']['lookup']['citations'].append(
            {'id': 'lookup:web2', 'title': '另一年份的学校资料', 'url': 'https://example.org/2026', 'articleId': ''})
        conflict = {'citation_ids': ['lookup:web1', 'lookup:web2'], 'description': '不同年份的统计口径待确认'}
        # Shape captured by the permitted public-source model replay: a writing
        # action claimed sufficient evidence, omitted IDs, and listed a conflict.
        bad = {'action': 'write_draft', 'draft_request': {'task_id': 'draft', 'instruction': '写介绍',
                'depends_on': ['lookup'], 'requires_evidence': True},
               'evidence_assessment': {'adequacy': 'sufficient', 'reason': '已有学校资料', 'conflicts': [conflict]}}
        with self.assertRaises(ValidationError) as caught:
            agent.MainDecision.model_validate(bad)
        self.assertEqual(caught.exception.errors(include_input=False)[0]['loc'], ('evidence_assessment', 'selected_ids'))
        good = agent.MainDecision(action='retrieve', evidence_assessment=agent.EvidenceAssessment(
            selected_ids=['lookup:web1', 'lookup:web2'], adequacy='partial', reason='需要核对统计口径',
            missing_aspects=['确认现行统计口径'], conflicts=[conflict]),
            retrieval=agent.RetrievalRequest(task_id='verify_data', instruction='核实学校最新官方统计口径',
                search_query='学校 官网 最新简介 统计口径', filters={}, allow_web=True))
        result, control = await self.decide([envelope(bad, error=caught.exception), envelope(good.model_dump(), good)], state)
        repair = control.ainvoke.await_args_list[1].args[0][-1].content
        self.assertIn('evidence_assessment_contract', repair)
        self.assertIn('selected_ids_required_for_every_action', repair)
        self.assertIn('不要把格式修复默认变成answer拒答', repair)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(result['main_action'], 'retrieve')
        self.assertFalse(result.get('stop_reason'))
        self.assertEqual(result['plan']['tasks'][0]['search_query'], good.retrieval.search_query)
        self.assertEqual(state['task_results']['lookup']['status'], 'succeeded')
        issue = result['decision_contract_audit']['failures'][0]['issues'][0]
        self.assertEqual(issue, {'path': 'evidence_assessment.selected_ids', 'type': 'missing'})

    async def test_unresolved_conflict_rule_is_preserved_in_safe_failure_audit(self):
        state = self.state()
        state['task_results']['lookup']['citations'].append(
            {'id': 'lookup:web2', 'title': '资料二', 'url': 'https://example.org/b', 'articleId': ''})
        bad = none_answer().model_dump()
        bad['evidence_assessment'].update(selected_ids=['lookup:web1', 'lookup:web2'], adequacy='sufficient',
            missing_aspects=[], conflicts=[{'citation_ids': ['lookup:web1', 'lookup:web2'], 'description': '版本不同'}])
        with self.assertRaises(ValidationError) as caught:
            agent.MainDecision.model_validate(bad)
        good = none_answer()
        result, _ = await self.decide([envelope(bad, error=caught.exception), envelope(good.model_dump(), good)], state)
        issue = result['decision_contract_audit']['failures'][0]['issues'][0]
        self.assertEqual(issue['type'], 'evidence_unresolved_conflict')
        self.assertNotIn('版本不同', json.dumps(result['decision_contract_audit'], ensure_ascii=False))

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
