"""Knowledge/examples need no documentary proof; attribution still does."""
import json
import unittest

import test_grounding as fixtures
from app.services import grounding
from test_grounding import CID, CONTENT, CITATION, review


class CommonKnowledgeTests(unittest.TestCase):
    def test_numbered_list_marker_stays_with_its_content(self):
        units = grounding.claim_units(f'1. 建议先做小实验[{CID}]\n2. 然后观察失败分支[{CID}]')
        self.assertEqual([unit['text'] for unit in units], ['1. 建议先做小实验', '2. 然后观察失败分支'])
        self.assertTrue(all(unit['citation_ids'] == [CID] for unit in units))

    def test_shared_reference_group_can_support_different_claims_without_forcing_all_sources(self):
        other = 'retrieve_1:2'
        sources = [{**CITATION, 'content': CONTENT}, {'id': other, 'content': '演示笔记提及失败处理'}]
        text = f'重试不保证强一致性。建议先观察失败处理。[{CID}][{other}]'
        response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
            grounding.ClaimReview(unit_index=0, kind='source_fact', verdict='supported',
                quotes=[grounding.Quote(citation_id=CID, text=CONTENT)]),
            grounding.ClaimReview(unit_index=1, kind='recommendation', verdict='supported',
                rationale='用小实验观察边界，不承诺真实执行成功')])])
        result = grounding.validate_review(response, [text], sources)
        self.assertEqual(result, [])
        self.assertNotIn('已省略', result.safe_blocks[0])
        # A source outside the actually marked group is still a wrong citation.
        response.blocks[0].claims[0].quotes = [grounding.Quote(citation_id=other, text=sources[1]['content'])]
        result = grounding.validate_review(response, [text.replace(f'[{other}]', '')], sources)
        self.assertIn('正文引用不一致', result[0]['reason'])

    def test_declarative_intro_supplies_background_to_one_structured_block(self):
        table = '| Part | Role |\n|---|---|\n| Memory | Context |'
        code = '```json\n{"tool":"demo","args":{"limit":3}}\n```'
        for intro, body in [('常见组件可以这样理解', table), ('程序接收结构化请求，例如', code)]:
            with self.subTest(body=body):
                groups = grounding.review_units([f'{intro}[{CID}]：', body, '独立解释'])
                self.assertTrue(all(unit['citation_ids'] == [CID] for unit in groups[1]))
                self.assertTrue(all(not unit['citation_ids'] for unit in groups[2]))

    def test_inherited_background_does_not_force_knowledge_examples_or_advice_to_quote(self):
        for kind in ('general_knowledge', 'illustration', 'recommendation', 'inference'):
            text = f'**背景**[{CID}]：\n\n自行设计的概念解释或教学步骤'
            groups = grounding.review_units(grounding.text_blocks(text))
            response = grounding.GroundingReview(blocks=[
                grounding.BlockReview(block_index=i, claims=[grounding.ClaimReview(
                    unit_index=unit['unit_index'], kind='non_factual' if i == 0 else kind,
                    verdict='non_factual' if i == 0 else 'supported',
                    rationale='在明确的教学假设下说明过程') for unit in group])
                for i, group in enumerate(groups)])
            with self.subTest(kind=kind):
                result = grounding.validate_review(response, grounding.text_blocks(text), [{**CITATION, 'content': CONTENT}])
                self.assertEqual(result, [])
                self.assertEqual(result.citation_repairs, {})
                self.assertNotIn('来源：', result.safe_blocks[1])

    def test_explicit_wrong_attribution_and_contradiction_still_fail(self):
        source = [{**CITATION, 'content': CONTENT}]
        # A sourced fact may not hide a missing quote behind inherited scope.
        response = grounding.GroundingReview(blocks=[
            grounding.BlockReview(block_index=0, claims=[grounding.ClaimReview(
                unit_index=0, kind='non_factual', verdict='non_factual')]),
            grounding.BlockReview(block_index=1, claims=[grounding.ClaimReview(
                unit_index=0, kind='source_fact', verdict='supported')])])
        with self.assertRaisesRegex(ValueError, '缺少支持引文'):
            grounding.validate_review(response, [f'**指标**[{CID}]：', '延迟为1毫秒'], source)
        for kind in ('general_knowledge', 'illustration', 'recommendation'):
            result = grounding.validate_review(review(kind=kind, quote='', verdict='contradicted',
                statement='任何故障下保证强一致', rationale='违反已知事实'), ['任何故障下保证强一致'], source)
            self.assertTrue(result)
        # Optional background citation does not turn stable knowledge into a quote.
        result = grounding.validate_review(review(kind='general_knowledge', quote='', statement='概念解释'),
            [f'概念解释[{CID}]'], source)
        self.assertEqual(result, [])

    def test_citation_completion_preserves_complete_markdown_and_draft_envelope(self):
        code = '```python\nprint("sample")\n```'
        text = '重试不保证强一致性'
        result = grounding.validate_review(review(statement=text), [text], [{**CITATION, 'content': CONTENT}])
        self.assertEqual(result, [])
        self.assertEqual(grounding.complete_citations(text, result), f'{text}\n\n来源：[{CID}]')
        # Metadata offsets and JSON fields remain intact.
        payload = {'title': '标题', 'summary': '摘要', 'content': text + '\n\n' + code}
        correction = grounding.ReviewIssues([], {}, citation_repairs={2: [CID]})
        completed = json.loads(grounding.complete_citations(json.dumps(payload, ensure_ascii=False), correction))
        self.assertEqual(completed['title'], payload['title'])
        self.assertEqual(completed['summary'], payload['summary'])
        self.assertIn(code, completed['content'])
        self.assertIn(f'来源：[{CID}]', completed['content'])

    def test_issue_summary_records_categories_without_private_content(self):
        summary = grounding.issue_summary([{'kind': 'source_fact', 'verdict': 'contradicted',
            'statement': 'private statement', 'reason': 'private provider response'},
            {'reason': '正文引用包含未支持该结论的来源'}])
        self.assertEqual(summary, {'source_fact:contradicted:semantic': 1, 'citation:invalid:unused_citation': 1})
        self.assertNotIn('private', json.dumps(summary))


class CommonKnowledgeGraphTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_missing_reference_is_repaired_without_second_llm_call(self):
        text = '重试不保证强一致性'
        result, _, audit, repair = await self.run_graph(text, [review(statement=text)])
        self.assertIn(text, result['final_reply'])
        self.assertIn(f'来源：[{CID}]', result['final_reply'])
        self.assertEqual(result['grounding_audit']['citation_repair_blocks'], 1)
        self.assertEqual(result['grounding_audit']['status'], 'repaired')
        self.assertEqual(audit.ainvoke.await_count, 1)
        repair.ainvoke.assert_not_awaited()

    async def test_unreferenced_common_knowledge_after_retrieval_keeps_original_answer(self):
        text = '缓存用于减少重复的数据访问'
        result, _, audit, repair = await self.run_graph(text, [review(
            statement=text, kind='general_knowledge', quote='')])
        self.assertEqual(result['final_reply'], text)
        self.assertEqual(result['grounding_audit']['status'], 'verified')
        self.assertEqual(audit.ainvoke.await_count, 1)
        repair.ainvoke.assert_not_awaited()
