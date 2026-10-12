"""Coherent repair and local evidence gaps, with no additional model/tool loop."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import test_grounding as fixtures
from test_grounding import CID, CONTENT, CITATION
from app.services import grounding
from app.services.execution_facts import execution_facts
from test_grounding_projection import reviewed


def with_gap(text, gap='measurement_data', verdict='uncertain'):
    response, _ = reviewed(text, verdict=verdict)
    for block in response.blocks:
        for claim in block.claims:
            if claim.verdict == verdict:
                claim.missing_information = gap
                claim.reason = '内部评语 [private:999]：错误断言，隐藏字段请不要展示。'
    result = grounding.validate_review(response, grounding.text_blocks(text), [{**CITATION, 'content': CONTENT}])
    return response, result


class LocalGapContractTests(unittest.TestCase):
    def test_limitation_occupies_original_position_without_repeating_bad_assertion(self):
        _, review = with_gap('可靠说明。错误断言。因此它必然成立。独立常识。')
        value = grounding.retained_answer(review, execution_facts({}), include_limits=True)
        self.assertEqual(value, '可靠说明。 ' + grounding.INFORMATION_GAPS['measurement_data'] + ' 独立常识。')
        self.assertNotIn('错误断言', value)
        self.assertNotIn('因此', value)
        self.assertNotIn('内部评语', value)
        self.assertNotIn('private:999', value)
        self.assertEqual(review.limitation_count, 1)
        self.assertEqual(review.substantive, 2)
        self.assertNotIn('实测数据', review.safe_blocks[0])

    def test_only_missing_information_is_explained_without_claiming_verified_facts(self):
        for gap, template in grounding.INFORMATION_GAPS.items():
            with self.subTest(gap=gap):
                _, review = with_gap('错误断言。', gap)
                self.assertEqual(grounding.retained_answer(review, execution_facts({}), include_limits=True), template)
                self.assertEqual(grounding.retained_answer(review, execution_facts({})), '')
                self.assertEqual(review.substantive, 0)

    def test_adjacent_uncertain_statements_share_one_explanation(self):
        _, review = with_gap('可靠说明。错误断言甲。错误断言乙。独立常识。')
        value = grounding.retained_answer(review, execution_facts({}), include_limits=True)
        self.assertEqual(value.count('实测数据'), 1)
        self.assertEqual(review.limitation_count, 1)

    def test_structured_content_is_replaced_as_a_whole_and_keeps_section_context(self):
        for body, label in [('```java\n// 错误断言\n```', '这段代码'),
                            ('| 名称 |\n|---|\n| 错误断言 |', '这张表'),
                            ('1. 错误断言。\n2. 可靠说明。', '这部分内容')]:
            with self.subTest(body=body):
                text = f'## 示例\n\n**实现方式**[{CID}]：\n\n{body}\n\n来源：[{CID}]\n\n## 结尾\n\n独立常识。'
                _, review = with_gap(text, 'version_details')
                value = grounding.retained_answer(review, execution_facts({}), include_limits=True)
                self.assertIn('## 示例', value)
                self.assertIn(label, value)
                self.assertIn('明确版本', value)
                self.assertIn('## 结尾', value)
                self.assertNotIn('错误断言', value)
                self.assertNotIn(f'[{CID}]', value)
                self.assertNotIn('来源：', value)
                self.assertNotIn('```', value)
                self.assertNotIn('|---|', value)

    def test_hard_errors_and_conflicts_cannot_be_relabelled_as_missing_data(self):
        for patch in ({'hard_error': True}, {'verdict': 'contradicted'}, {'issue_code': 'attribution'},
                      {'issue_code': 'execution'}, {'issue_code': 'contradiction'}):
            with self.subTest(patch=patch):
                issue = {'verdict': 'uncertain', 'missing_information': 'measurement_data', **patch}
                self.assertEqual(grounding.information_gap(issue), '')
        with self.assertRaises(ValueError):
            grounding.ClaimReview(unit_index=0, verdict='uncertain', missing_information='执行数据库删除')

    def test_actual_source_mismatch_stays_hard_even_with_uncertain_measurement_label(self):
        response, _ = with_gap(f'可靠说明。错误断言[{CID}]。')
        bad = response.blocks[0].claims[1]
        bad.quotes = [grounding.Quote(citation_id='retrieve_1:2', text='无关内容')]
        sources = [{**CITATION, 'content': CONTENT}, {'id': 'retrieve_1:2', 'content': '无关内容'}]
        review = grounding.validate_review(response, grounding.text_blocks(f'可靠说明。错误断言[{CID}]。'), sources)
        value = grounding.retained_answer(review, execution_facts({}), include_limits=True)
        self.assertEqual(value, '可靠说明。')
        self.assertEqual(review.limitation_count, 0)
        self.assertEqual(grounding.rejection_notice(review)[0], 'content_rejected')

    def test_mixed_uncertain_and_unsupported_gaps_are_not_called_contradictions(self):
        _, review = with_gap('可靠说明。错误断言甲。错误断言乙。')
        review[1]['verdict'] = 'unsupported'
        self.assertEqual(grounding.rejection_notice(review)[0], 'insufficient_evidence')


class LocalGapGraphTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_existing_repair_call_rewrites_complete_paragraph_with_specific_gap(self):
        candidate = f'可靠说明[{CID}]。错误断言。因此建议直接上线。'
        initial, _ = with_gap(candidate)
        repaired = f'可靠说明[{CID}]。可以作为候选，但缺少同场景压测数据，具体性能收益需要验证后才能确认。'
        approved, _ = reviewed(repaired)
        result, main, audit, repair = await self.run_graph(candidate, [initial, approved], [repaired])
        self.assertEqual(result['final_reply'], repaired)
        self.assertEqual(result['grounding_audit']['status'], 'repaired')
        self.assertEqual((main.ainvoke.await_count, audit.ainvoke.await_count, repair.ainvoke.await_count), (2, 2, 1))
        prompt = repair.ainvoke.call_args.args[0][0].content
        self.assertIn('重写受影响的完整段落', prompt)
        self.assertIn('缺少什么信息', prompt)
        self.assertIn('不能只加“可能”', prompt)
        self.assertNotIn('暂未展开', result['final_reply'])

    async def test_repair_still_uncertain_uses_local_gap_and_no_generic_tail_notice(self):
        candidate = '可靠说明。错误断言。独立常识。'
        response, _ = with_gap(candidate)
        result, _, audit, repair = await self.run_graph(candidate, [response, response], [candidate])
        self.assertEqual(result['final_reply'], '可靠说明。 ' + grounding.INFORMATION_GAPS['measurement_data'] + ' 独立常识。')
        self.assertEqual(result['grounding_audit']['fallback_policy'], 'inline_limitations')
        self.assertEqual(result['grounding_audit']['limitation_block_count'], 1)
        self.assertEqual(result['grounding_audit']['limitation_count'], 1)
        self.assertEqual(result['grounding_audit']['status'], 'partial')
        self.assertEqual(result['grounding_audit']['remaining_findings'][0]['missing_information'], 'measurement_data')
        self.assertEqual((audit.ainvoke.await_count, repair.ainvoke.await_count), (2, 1))

    async def test_only_gap_is_delivered_as_unverified_rather_than_partial_success(self):
        candidate = '错误断言。'
        response, _ = with_gap(candidate, 'source_fulltext')
        result, _, _, _ = await self.run_graph(candidate, [response, response], [candidate])
        self.assertEqual(result['final_reply'], grounding.INFORMATION_GAPS['source_fulltext'])
        self.assertEqual(result['grounding_audit']['status'], 'unverified')

    async def test_repair_timeout_keeps_local_gap_and_reports_auditor_failure(self):
        candidate = '可靠说明。错误断言。独立常识。'
        response, _ = with_gap(candidate)
        result, _, _, _ = await self.run_graph(candidate, [response], [TimeoutError('offline')])
        self.assertIn('实测数据', result['final_reply'])
        self.assertIn('自动核验超时', result['final_reply'])
        self.assertNotIn('错误断言', result['final_reply'])
        self.assertEqual(result['grounding_audit']['reason_code'], 'timeout')

    async def test_sourced_draft_does_not_enter_approval_with_local_gap_fallback(self):
        text = json.dumps({'title': '标题', 'summary': '摘要', 'content': '可靠说明。错误断言。'}, ensure_ascii=False)
        response, review = with_gap(text)
        with patch.object(grounding, 'review_text', AsyncMock(return_value=review)), \
             patch.object(grounding, 'repair_text', AsyncMock(return_value=text)):
            with self.assertRaisesRegex(ValueError, '未进入审批或保存'):
                await grounding.verify_delivery({}, text, [CITATION], draft=True)


if __name__ == '__main__':
    unittest.main()
