"""A matching quotation is not an override for an auditor's factual objection."""
import unittest

import test_grounding as fixtures
from test_grounding import CID, CITATION, review, source_result
from app.services import grounding


BAD_SOURCE = '这份演示笔记写道：2+2=5。'


class SourceQualityEvaluationTests(unittest.TestCase):
    def test_negative_claim_is_not_confused_with_adopting_the_claim(self):
        from evaluation.grounding import unqualified_claim_present
        phrase = '可信度为100%'
        self.assertTrue(unqualified_claim_present('因为排第一，所以可信度为100%。', phrase))
        self.assertTrue(unqualified_claim_present('不能联网，但可信度为100%。', phrase))
        self.assertFalse(unqualified_claim_present('也不能据此得出可信度为100%的结论。', phrase))
        self.assertFalse(unqualified_claim_present('“可信度为100%”是错误的。', phrase))
        self.assertTrue(unqualified_claim_present('不能证明可信度为100%。但实际可信度为100%。', phrase))


class SourceQualityGraphTests(unittest.IsolatedAsyncioTestCase):
    run_graph = fixtures.GroundingGraphTests.run_graph

    async def test_exact_quote_does_not_override_obvious_error_verdict(self):
        candidate = f'2+2=5是正确的算式。[{CID}]'
        repaired = '正确结果是2+2=4。'
        rejected = review(verdict='contradicted', quote=BAD_SOURCE)
        accepted = review(quote='', kind='general_knowledge')
        retrieved = {**source_result(), 'citations': [{**CITATION, 'excerpt': BAD_SOURCE}],
                     'citation_contents': {CID: BAD_SOURCE}, 'rag_context': f'[{CID}] {BAD_SOURCE}'}
        result, _, audit, repair = await self.run_graph(candidate, [rejected, accepted], [repaired], retrieved=retrieved)
        self.assertEqual(result['final_reply'], repaired)
        self.assertEqual(result['grounding_audit']['status'], 'repaired')
        self.assertEqual((audit.ainvoke.await_count, repair.ainvoke.await_count), (2, 1))

    async def test_reporting_and_correcting_an_erroneous_source_can_be_supported(self):
        text = f'笔记声称2+2=5。[{CID}]\n\n这个算式错误，2+2=4。'
        response = grounding.GroundingReview(blocks=[
            grounding.BlockReview(block_index=0, claims=[grounding.ClaimReview(unit_index=0,
                kind='source_fact', verdict='supported', quotes=[grounding.Quote(citation_id=CID, text=BAD_SOURCE)])]),
            grounding.BlockReview(block_index=1, claims=[grounding.ClaimReview(unit_index=0,
                kind='general_knowledge', verdict='supported')]),
        ])
        retrieved = {**source_result(), 'citations': [{**CITATION, 'excerpt': BAD_SOURCE}],
                     'citation_contents': {CID: BAD_SOURCE}, 'rag_context': f'[{CID}] {BAD_SOURCE}'}
        result, _, _, repair = await self.run_graph(text, [response], retrieved=retrieved)
        self.assertEqual(result['final_reply'], text)
        self.assertEqual(result['grounding_audit']['status'], 'verified')
        repair.ainvoke.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
