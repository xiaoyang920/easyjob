"""Exercise the real graph, bounded read recovery and deterministic text edits."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import test_grounding  # Initializes offline provider configuration.
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import action_runtime, builder, main_agent, staged_runtime
from app.graph.delivery_recovery import DeliveryLookup
from app.graph.state_factory import create_initial_state
from app.models.evidence_assessment import EvidenceAssessment
from app.services import grounding
from app.services.delivery_patch import GroundingPatch, apply_delivery_patch
from test_grounding import CID, CITATION, source_result


def gap(index=1, missing='supporting_source'):
    return {'block_index': index, 'unit_index': 0, 'kind': 'source_fact', 'verdict': 'unsupported',
            'issue_code': 'insufficient_evidence', 'missing_information': missing, 'hard_error': False,
            'statement': '该版本默认值为10', 'reason': '缺少该版本官方说明', 'citation_ids': [CID]}


class PatchTests(unittest.TestCase):
    def test_unchanged_whitespace_code_and_unicode_are_preserved_exactly(self):
        before = '  原文🙂  \r\n\r\n错误。\r\n\r\n```java\r\n\r\ncode();\r\n```\r\n\r\n结尾  \r\n'
        patch = GroundingPatch(replacements=[{'block_index': 1, 'issue_block_index': 1, 'text': '修正。'}])
        self.assertEqual(apply_delivery_patch(before, patch, [gap()]), before.replace('错误。', '修正。'))

    def test_dependent_paragraph_can_change_but_other_blocks_stay_unchanged(self):
        patch = {'replacements': [{'block_index': i, 'issue_block_index': 1, 'text': text}
                                  for i, text in [(1, '条件尚待确认。'), (3, '因此该建议需先确认条件。')]]}
        text = '开头。\n\n错误前提。\n\n无关内容。\n\n依赖前提的结论。'
        self.assertEqual(apply_delivery_patch(text, patch, [gap()]),
                         '开头。\n\n条件尚待确认。\n\n无关内容。\n\n因此该建议需先确认条件。')

    def test_duplicate_unknown_anchor_out_of_range_and_missing_problem_are_rejected(self):
        edit = {'block_index': 1, 'issue_block_index': 1, 'text': '修正'}
        for edits in ([edit, edit], [{**edit, 'block_index': 5}], [{**edit, 'issue_block_index': 0}],
                      [{**edit, 'block_index': 0}]):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                apply_delivery_patch('开头\n\n错误', {'replacements': edits}, [gap()])

    def test_draft_metadata_and_untouched_body_remain_intact(self):
        original = {'title': '原标题', 'summary': '原摘要', 'content': '正文\r\n\r\n错误。\r\n\r\n结尾🙂'}
        patch = {'replacements': [{'block_index': 3, 'issue_block_index': 3, 'text': '修正。'}]}
        result = json.loads(apply_delivery_patch(json.dumps(original), patch, [gap(3)]))
        self.assertEqual(result, {**original, 'content': original['content'].replace('错误。', '修正。')})

    def test_automatic_citation_completion_preserves_other_paragraphs(self):
        text = '  原文🙂  \r\n\r\n有据事实。\r\n\r\n结尾  \r\n'
        review = grounding.ReviewIssues([], {}, citation_repairs={1: [CID]})
        self.assertEqual(grounding.complete_citations(text, review),
            text.replace('有据事实。', f'有据事实。\n\n来源：[{CID}]'))

    def test_first_review_projection_survives_json_checkpoint_roundtrip(self):
        first = grounding.ReviewIssues([gap()], {0: '安全内容', 1: ''}, substantive=1,
            limited_blocks={0: '安全内容', 1: '需要补充资料。'}, limitation_blocks=[1], limitation_count=1)
        recovery = json.loads(json.dumps({'issues': list(first), 'review_projection': grounding.review_projection(first)}))
        restored = grounding.restore_review(recovery)
        self.assertEqual(restored.safe_blocks, first.safe_blocks)
        self.assertEqual(grounding.retained_answer(restored, {'retrievals': [], 'drafts': [], 'memory_write': 'not_submitted'}, include_limits=True),
            '安全内容\n\n需要补充资料。')


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, *, lookup=True, retrieve_error=None, missing='supporting_source',
                      remaining_issue=False, max_rounds=8, cancelled=False, checkpoint=False, repeat=False):
        candidate = f'稳定的通用解释。\r\n\r\n该版本默认值为10。[{CID}]\r\n\r\n所以建议启用。'
        state = create_initial_state(7, '说明此版本的默认值及建议', [])
        state.update(main_round=1, task_results={'retrieve_1': {
            **source_result(), 'kind': 'search', 'actor': 'main', 'retrieval_target': 'knowledge',
            'instruction': '原查询', 'result': '没有版本默认值', 'status': 'succeeded'}})
        answer = main_agent.MainDecision(action='answer', reply=candidate,
            evidence_assessment=EvidenceAssessment(selected_ids=[CID], adequacy='sufficient', reason='候选资料'))
        request = main_agent.RetrievalRequest(instruction='补查此版本官方默认值', search_query='版本 默认值 官方', filters={})
        if repeat:
            request = main_agent.RetrievalRequest(instruction='原查询', filters={})
            old = main_agent.compile_action_plan(main_agent.MainDecision(action='retrieve', retrieval=request), 1).tasks[0]
            state['action_history'] = [{'action': 'retrieve', 'task_ids': ['retrieve_1'], 'tasks': [old.model_dump()]}]
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=[answer, DeliveryLookup(retrieval=request if lookup else None)]))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        new_id = 'delivery_lookup_3:1'
        will_lookup = lookup and not retrieve_error and not repeat and max_rounds > 2 and missing in ('supporting_source', 'source_fulltext', 'version_details')
        fixed = f'该版本默认值为20。[{new_id}]' if will_lookup else '缺少该版本官方说明，目前不能确认具体默认值。'
        edits = GroundingPatch(replacements=[{'block_index': i, 'issue_block_index': 1, 'text': text}
            for i, text in [(1, fixed), (2, '建议先确认版本与配置，再决定是否启用。')]])
        patch_control = SimpleNamespace(ainvoke=AsyncMock(return_value=edits))
        patch_model = SimpleNamespace(with_structured_output=Mock(return_value=patch_control))
        issue = gap(missing=missing)
        reviewer = AsyncMock(side_effect=[HTTPException(409, 'cancelled') if cancelled else [issue],
                                          [issue] if remaining_issue else []])
        async def retrieve(context):
            if retrieve_error:
                raise retrieve_error
            self.assertEqual(context['current_task']['retrieval_target'], 'knowledge')
            self.assertNotIn('draft_generate', context['capabilities'])
            return {'status': 'succeeded', 'rag_context': f'[{new_id}] 官方默认值为20。',
                    'citations': [{**CITATION, 'id': new_id, 'excerpt': '官方默认值为20。'}],
                    'citation_contents': {new_id: '官方默认值为20。'}, 'article_cards': [],
                    'retrieval_report': {'assessment_owner': 'main', 'platform': {'status': 'found'},
                                         'web': {'status': 'not_requested'}}}
        retriever = AsyncMock(side_effect=retrieve)
        with patch.object(main_agent, 'get_llm', return_value=model), \
             patch.object(grounding, 'get_llm', return_value=patch_model), \
             patch.object(grounding, 'review_text', reviewer), \
             patch.object(action_runtime, 'retrieve_evidence', retriever), \
             patch.object(staged_runtime, 'verify_public_evidence', AsyncMock()), \
             patch.object(main_agent.settings, 'MAIN_MAX_ROUNDS', max_rounds):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver(),
                interrupt_after=['final_gate'] if checkpoint else None)
            config = {'configurable': {'thread_id': self.id()}, 'recursion_limit': 40}
            if cancelled:
                with self.assertRaises(HTTPException):
                    await graph.ainvoke(state, config=config)
                retriever.assert_not_awaited()
                patch_control.ainvoke.assert_not_awaited()
                return
            result = await graph.ainvoke(state, config=config)
            if checkpoint:
                self.assertEqual(result['delivery_review']['phase'], 'needs_retrieval')
                self.assertEqual(reviewer.await_count, 1)
                result = await graph.ainvoke(None, config=config)
        return result, control, reviewer, retriever, patch_control, candidate

    async def test_gap_returns_to_main_once_and_patches_with_new_raw_evidence(self):
        result, main, review, retrieval, repair, candidate = await self.execute()
        self.assertEqual((main.ainvoke.await_count, review.await_count, retrieval.await_count, repair.ainvoke.await_count), (2, 2, 1, 1))
        self.assertTrue(result['final_reply'].startswith('稳定的通用解释。\r\n\r\n'))
        self.assertIn('默认值为20', result['final_reply'])
        self.assertIn('delivery_lookup_3:1', result['final_reply'])
        self.assertEqual(result['grounding_audit']['lookup_count'], 1)
        self.assertEqual(result['grounding_audit']['lookup_status'], 'succeeded')
        self.assertEqual(result['delivery_review']['phase'], 'complete')
        payload = json.loads(repair.ainvoke.await_args.args[0][1].content)
        self.assertEqual(payload['text'], candidate)
        self.assertIn('官方默认值为20。', [s['content'] for s in payload['sources']])
        self.assertEqual(review.await_args.args[0], result['final_reply'])
        self.assertEqual(result['task_results']['retrieve_1']['result'], '没有版本默认值')

    async def test_timeout_does_not_loop_and_repairs_with_existing_sources(self):
        result, main, review, retrieval, repair, _ = await self.execute(retrieve_error=TimeoutError())
        self.assertEqual(retrieval.await_count, 1)
        self.assertEqual((review.await_count, repair.ainvoke.await_count), (2, 1))
        self.assertEqual(result['grounding_audit']['lookup_status'], 'tool_error')
        self.assertIn('目前不能确认', result['final_reply'])

    async def test_main_can_decline_lookup_without_regenerating_answer(self):
        result, main, review, retrieval, repair, _ = await self.execute(lookup=False)
        retrieval.assert_not_awaited()
        self.assertEqual(main.ainvoke.await_count, 2)
        self.assertEqual(result['grounding_audit']['lookup_count'], 0)
        self.assertEqual(repair.ainvoke.await_count, 1)

    async def test_repeated_strategy_is_blocked_before_execution(self):
        result, _, _, retrieval, repair, _ = await self.execute(repeat=True)
        retrieval.assert_not_awaited()
        self.assertEqual(result['grounding_audit']['lookup_status'], 'budget_or_repeat_limit')
        self.assertEqual(repair.ainvoke.await_count, 1)

    async def test_no_extra_lookup_when_budget_exhausted_or_personal_measurements_missing(self):
        for kwargs in ({'max_rounds': 2}, {'missing': 'measurement_data'}, {'missing': 'user_context'}):
            with self.subTest(kwargs=kwargs):
                result, main, review, retrieval, repair, _ = await self.execute(**kwargs)
                retrieval.assert_not_awaited()
                self.assertEqual(main.ainvoke.await_count, 1)
                self.assertEqual((review.await_count, repair.ainvoke.await_count), (2, 1))

    async def test_failed_second_review_never_requests_a_second_lookup(self):
        result, main, review, retrieval, repair, _ = await self.execute(remaining_issue=True)
        self.assertEqual((main.ainvoke.await_count, review.await_count, retrieval.await_count, repair.ainvoke.await_count), (2, 2, 1, 1))
        self.assertEqual(result['grounding_audit']['status'], 'unverified')

    async def test_review_cancellation_stops_before_recovery(self):
        await self.execute(cancelled=True)

    async def test_checkpoint_resume_does_not_repeat_the_first_review(self):
        result, _, review, retrieval, repair, _ = await self.execute(checkpoint=True)
        self.assertEqual(result['delivery_review']['phase'], 'complete')
        self.assertEqual((review.await_count, retrieval.await_count, repair.ainvoke.await_count), (2, 1, 1))

    def test_recovery_schema_cannot_request_private_memory_drafts_or_writes(self):
        for payload in ({'retrieval': {'target': 'memory', 'instruction': 'read'}},
                        {'retrieval': {'target': 'drafts', 'instruction': 'read'}},
                        {'action': 'write_draft', 'draft_request': {}}, {'memory_changes': []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                DeliveryLookup.model_validate(payload)

    def test_new_turn_resets_recovery_state(self):
        self.assertEqual(create_initial_state(7, '下一轮', [])['delivery_review'], {})

    async def test_execution_error_patch_keeps_unrelated_paragraph_exact(self):
        control = SimpleNamespace(ainvoke=AsyncMock(return_value=GroundingPatch(replacements=[
            {'block_index': 1, 'issue_block_index': 1, 'text': '尚未保存草稿。'}])))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        text = '  有效解释🙂 \r\n\r\n草稿已保存到草稿箱。'
        facts = {'retrievals': [], 'drafts': [], 'memory_write': 'not_submitted'}
        with patch.object(grounding, 'get_llm', return_value=model):
            repaired = await grounding.repair_text(text, [], facts, ['没有草稿保存成功记录'])
        self.assertEqual(repaired, text.replace('草稿已保存到草稿箱。', '尚未保存草稿。'))
