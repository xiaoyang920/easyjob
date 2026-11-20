"""Sentence-level salvage, uncertainty notices and intact structured output."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import test_grounding as fixtures
from test_grounding import CID, CONTENT, CITATION
from app.graph.state_factory import create_initial_state
from app.services import grounding
from app.services.execution_facts import execution_facts


def reviewed(text, bad='错误断言', verdict='uncertain', *, cited_fact=False):
    blocks = grounding.text_blocks(text)
    metadata = (0, 1) if grounding.draft_payload(text) else ()
    response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=i, claims=[
        grounding.ClaimReview(unit_index=unit['unit_index'],
            kind='source_fact' if bad in unit['text'] or cited_fact and '可靠说明' in unit['text'] else 'general_knowledge',
            verdict=verdict if bad in unit['text'] else 'supported',
            issue_code='insufficient_evidence' if bad in unit['text'] else 'none',
            quotes=[grounding.Quote(citation_id=CID, text=CONTENT)] if cited_fact and '可靠说明' in unit['text'] else [])
        for unit in group]) for i, group in enumerate(grounding.review_units(blocks, metadata_indices=metadata))])
    return response, grounding.validate_review(response, blocks, [{**CITATION, 'content': CONTENT}], metadata_indices=metadata)


class ProjectionContractTests(unittest.TestCase):
    def test_scope_notice_survives_one_uncertain_sentence_in_same_paragraph(self):
        text = '**资料说明**：网页只有搜索摘要，尚未核验全文。某接口的错误断言。具体参数请再查阅原文。'
        _, result = reviewed(text)
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertIn('**资料说明**：网页只有搜索摘要，尚未核验全文。', retained)
        self.assertIn('具体参数请再查阅原文。', retained)
        self.assertNotIn('错误断言', retained)
        self.assertNotIn('已省略', retained)
        self.assertEqual(result.partial_blocks, [0])
        self.assertEqual(result.omitted_blocks, [])
        self.assertEqual(result.omitted_sentences, 1)
        self.assertEqual(result.substantive, 2)

    def test_postfix_citation_is_kept_and_shared_citation_is_restored(self):
        for text in (f'可靠说明。[{CID}] 错误断言。[{CID}] 独立常识。',
                     f'可靠说明。错误断言[{CID}]。独立常识。'):
            with self.subTest(text=text):
                _, result = reviewed(text, cited_fact=True)
                retained = grounding.retained_answer(result, execution_facts({}))
                self.assertIn('可靠说明。', retained)
                self.assertIn(f'[{CID}]', retained)
                self.assertNotIn('错误断言', retained)

    def test_parentheses_and_bold_are_never_cut_into_fragments(self):
        for bad in ('风险说明（其中有错误断言。仍在同一括号内）。', '**风险说明（错误断言）**。'):
            text = '可靠说明。' + bad + '独立常识。'
            _, result = reviewed(text)
            retained = grounding.retained_answer(result, execution_facts({}))
            self.assertIn('可靠说明。', retained)
            self.assertIn('独立常识。', retained)
            self.assertNotIn('风险说明', retained)
            self.assertNotIn('（', retained)
            self.assertNotIn('**', retained)

    def test_quoted_sentences_and_closing_emphasis_stay_balanced(self):
        for quoted in ('"错误断言。仍是引语"。', "'错误断言。仍是引语'。", "'don't accept 错误断言。仍是引语'。", '“错误断言。仍是引语”。'):
            with self.subTest(quoted=quoted):
                _, result = reviewed('**可靠说明。**' + quoted + '独立常识。')
                retained = grounding.retained_answer(result, execution_facts({}))
                self.assertIn('**可靠说明。**', retained)
                self.assertIn('独立常识。', retained)
                self.assertNotIn('引语', retained)

    def test_semicolon_condition_and_dependent_followup_leave_no_detached_conclusion(self):
        text = '若存在错误断言；则这里依赖该前提。因此它必然成立。独立常识。'
        _, result = reviewed(text)
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertEqual(retained, '独立常识。')
        self.assertEqual(result.omitted_sentences, 2)
        self.assertEqual(result.substantive, 1)

    def test_code_table_list_html_and_unbalanced_paragraphs_are_not_spliced(self):
        for structural in ('```java\n// 可靠说明\n// 错误断言\n```',
                           '| 说明 | 结论 |\n|---|---|\n| 可靠说明 | 错误断言 |',
                           '1. 可靠说明。\n2. 错误断言。',
                           '<p>可靠说明。错误断言。</p>', '（可靠说明。错误断言。'):
            with self.subTest(structural=structural):
                _, result = reviewed('独立常识。\n\n## 问题章节\n\n' + structural)
                retained = grounding.retained_answer(result, execution_facts({}))
                self.assertEqual(retained, '独立常识。')
                self.assertEqual(result.omitted_blocks, [2])

    def test_empty_section_and_intro_are_removed_without_consuming_next_section(self):
        text = '## 保留\n\n可靠说明。\n\n## 示例\n\n**示例代码**：\n\n```text\n错误断言\n```\n\n## 结尾\n\n独立常识。'
        _, result = reviewed(text)
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertIn('## 保留', retained)
        self.assertIn('## 结尾', retained)
        self.assertNotIn('## 示例', retained)
        self.assertNotIn('**示例代码**', retained)
        self.assertNotIn('```', retained)

    def test_valid_table_footer_survives_but_failed_table_footer_does_not(self):
        table = '| 名称 |\n|---|\n| 可靠说明 |'
        _, result = reviewed(table + f'\n\n来源：[{CID}]')
        self.assertIn(f'来源：[{CID}]', grounding.retained_answer(result, execution_facts({})))
        _, result = reviewed('独立常识。\n\n' + table.replace('可靠说明', '错误断言') + f'\n\n来源：[{CID}]')
        self.assertEqual(grounding.retained_answer(result, execution_facts({})), '独立常识。')

    def test_structured_diagnostics_store_locations_and_codes_not_private_text(self):
        _, result = reviewed('可靠说明。含隐私的错误断言。')
        findings = grounding.issue_locations(result)
        self.assertEqual(findings[0]['issue_code'], 'insufficient_evidence')
        self.assertEqual(findings[0]['unit_index'], 1)
        self.assertNotIn('隐私', json.dumps(findings, ensure_ascii=False))
        result[0]['hard_error'] = True
        self.assertEqual(grounding.rejection_notice(result)[0], 'content_rejected')


class ProjectionGraphTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_uncertain_notice_preserves_scope_sentences_with_bounded_calls(self):
        text = '**资料说明**：目前只有摘要。这里有错误断言。具体细节尚待确认。'
        response, _ = reviewed(text)
        result, _, audit, repair = await self.run_graph(text, [response, response], [text])
        self.assertIn('**资料说明**：目前只有摘要。', result['final_reply'])
        self.assertIn('具体细节尚待确认。', result['final_reply'])
        self.assertNotIn('错误断言', result['final_reply'])
        self.assertNotIn('已省略', result['final_reply'])
        self.assertIn('现有资料不足以确认这一点', result['final_reply'])
        self.assertLess(result['final_reply'].index('现有资料不足以确认这一点'), result['final_reply'].index('具体细节尚待确认'))
        self.assertNotIn('暂未展开', result['final_reply'])
        self.assertEqual(result['grounding_audit']['reason_code'], 'evidence_uncertain')
        self.assertEqual(result['grounding_audit']['partial_block_count'], 1)
        self.assertEqual(result['grounding_audit']['omitted_sentence_count'], 1)
        self.assertEqual(result['grounding_audit']['status'], 'partial')
        self.assertEqual(result['grounding_audit']['limitation_count'], 1)
        self.assertEqual((audit.ainvoke.await_count, repair.ainvoke.await_count), (2, 1))

    async def test_unsupported_and_contradicted_have_distinct_notices_and_no_bad_assertion(self):
        text = '可靠说明。错误断言。'
        for verdict, code in [('unsupported', 'insufficient_evidence'), ('contradicted', 'content_rejected')]:
            with self.subTest(verdict=verdict):
                response, _ = reviewed(text, verdict=verdict)
                result, _, _, _ = await self.run_graph(text, [response, response], [text])
                self.assertEqual(result['grounding_audit']['reason_code'], code)
                self.assertIn('可靠说明。', result['final_reply'])
                self.assertNotIn('错误断言', result['final_reply'])

    async def test_uncertainty_with_no_safe_answer_returns_limit_not_error_or_raw_claim(self):
        text = '错误断言。'
        response, _ = reviewed(text)
        result, _, _, _ = await self.run_graph(text, [response, response], [text])
        self.assertNotIn('错误断言', result['final_reply'])
        self.assertIn('不足以确认', result['final_reply'])
        self.assertEqual(result['grounding_audit']['reason_code'], 'evidence_uncertain')
        self.assertEqual(result['grounding_audit']['status'], 'unverified')

    async def test_uncertain_draft_still_blocks_approval_instead_of_saving_partial_content(self):
        state = create_initial_state(7, '写文章', [])
        text = json.dumps({'title': '标题', 'summary': '摘要', 'content': '可靠说明。错误断言。'}, ensure_ascii=False)
        _, review = reviewed(text)
        with patch.object(grounding, 'review_text', AsyncMock(return_value=review)), \
             patch.object(grounding, 'repair_text', AsyncMock(return_value=text)):
            with self.assertRaisesRegex(ValueError, '尚无法确认.*未进入审批或保存'):
                await grounding.verify_delivery(state, text, [CITATION], draft=True)


if __name__ == '__main__':
    unittest.main()
