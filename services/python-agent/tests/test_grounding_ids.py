"""Server IDs and realistic Markdown, with no live model or network access."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_grounding as fixtures
from app.services import grounding
from app.services.execution_facts import execution_facts

SOURCE = {'id': 'retrieve_1:1', 'content': 'A cache miss loads from the database. Failed invalidation needs retry. Retry does not guarantee strong consistency.'}
CODE = '''```java
public void update(Item item) {
    database.update(item);

    try {
        cache.invalidate(item.id());
    } catch (RuntimeException error) {
        retryQueue.enqueue(item.id());
    }
}
```'''
TABLE = '| Condition | Suggestion |\n|---|---|\n| Short stale reads acceptable | Validate retry |\n| Strict reads required | Use authoritative storage |'
ANSWER = ('## Explanation\n\nFailed invalidation needs retry.[retrieve_1:1]\n\n'
          '## Illustrative code\n\n' + CODE + '\n\n## Conditional options\n\n' + TABLE)


def response_for(text, *, unknown=False):
    catalog = grounding.evidence_catalog([SOURCE])
    blocks = []
    for i, group in enumerate(grounding.review_units(grounding.text_blocks(text))):
        claims = []
        for unit in group:
            cited = bool(unit['citation_ids'])
            claims.append(grounding.ClaimReview(unit_index=unit['unit_index'],
                kind='source_fact' if cited else 'general_knowledge', verdict='supported',
                evidence_ids=['unknown' if unknown else next(iter(catalog))] if cited else []))
        blocks.append(grounding.BlockReview(block_index=i, claims=claims))
    return grounding.GroundingReview(blocks=blocks)


class ServerIdTests(unittest.TestCase):
    def test_code_and_table_are_not_copied_into_review_response_and_remain_intact(self):
        response = response_for(ANSWER)
        self.assertNotIn('database.update', response.model_dump_json())
        result = grounding.validate_review(response, grounding.text_blocks(ANSWER), [SOURCE],
                                            catalog=grounding.evidence_catalog([SOURCE]))
        self.assertEqual(result, [])
        self.assertEqual('\n\n'.join(result.safe_blocks.values()), ANSWER)

    def test_unknown_evidence_missing_units_and_wrong_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '未知依据编号'):
            grounding.validate_review(response_for(ANSWER, unknown=True), grounding.text_blocks(ANSWER), [SOURCE],
                                      catalog=grounding.evidence_catalog([SOURCE]))
        response = response_for(ANSWER)
        response.blocks[-1].claims.pop()
        with self.assertRaisesRegex(ValueError, '覆盖所有正文单元'):
            grounding.validate_review(response, grounding.text_blocks(ANSWER), [SOURCE],
                                      catalog=grounding.evidence_catalog([SOURCE]))
        response = response_for('Failed invalidation needs retry.[retrieve_1:1]')
        other = {'id': 'retrieve_1:2', 'content': SOURCE['content']}
        result = grounding.validate_review(response, ['Failed invalidation needs retry.[retrieve_1:1]'],
            [SOURCE, other], catalog=grounding.evidence_catalog([other]))
        self.assertIn('正文引用不一致', result[0]['reason'])

    def test_bad_table_is_omitted_whole_while_verified_code_keeps_fences(self):
        response = response_for(ANSWER)
        response.blocks[-1].claims[-1].verdict = 'unsupported'
        result = grounding.validate_review(response, grounding.text_blocks(ANSWER), [SOURCE],
                                            catalog=grounding.evidence_catalog([SOURCE]))
        retained = grounding.retained_answer(result, execution_facts({}))
        self.assertIn(CODE, retained)
        self.assertNotIn('|---|', retained)


class ServerIdGraphTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_complete_code_survives_auditor_timeout_without_raw_source_dump(self):
        result, _, _, repair = await self.run_graph(ANSWER, [TimeoutError('injected')])
        self.assertTrue(result['final_reply'].startswith(ANSWER))
        self.assertIn(CODE, result['final_reply'])
        self.assertIn(TABLE, result['final_reply'])
        self.assertNotIn('以下仅为', result['final_reply'])
        self.assertNotIn(fixtures.CONTENT, result['final_reply'])
        self.assertEqual(result['grounding_audit']['status'], 'verification_unavailable')
        repair.ainvoke.assert_not_awaited()

    async def test_false_execution_claim_and_no_evidence_do_not_use_answer_fallback(self):
        for candidate, assessment in [
            ('草稿已保存到草稿箱。', None),
            ('平台根本不存在相关文章。', fixtures.EvidenceAssessment(selected_ids=[], adequacy='none', reason='无匹配')),
        ]:
            state = fixtures.create_initial_state(7, 'test', [])
            if assessment:
                state['main_decision'] = {'evidence_assessment': assessment.model_dump()}
            with patch.object(grounding, 'review_text', AsyncMock(side_effect=TimeoutError('injected'))):
                text, audit = await grounding.verify_delivery(state, candidate, [fixtures.CITATION])
            self.assertNotIn(candidate, text)
            self.assertNotIn('fallback_policy', audit)

    async def test_large_review_uses_ids_and_output_budget_proportional_to_unit_count(self):
        answer = '\n\n'.join(f'General example {i}.' for i in range(60))
        response = response_for(answer)
        control = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        model = SimpleNamespace(with_structured_output=lambda *args, **kwargs: control)
        with patch.object(grounding, 'get_llm', return_value=model) as get_llm:
            result = await grounding.review_text(answer, [SOURCE], execution_facts({}))
        self.assertEqual(result, [])
        self.assertGreater(get_llm.call_args.kwargs['max_tokens'], 4096)
        payload = json.loads(control.ainvoke.await_args.args[0][1].content)
        self.assertTrue(payload['evidence_catalog'])
        self.assertIn('不要重抄正文', control.ainvoke.await_args.args[0][0].content)


if __name__ == '__main__':
    unittest.main()
