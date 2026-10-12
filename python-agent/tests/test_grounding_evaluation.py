import unittest
from evaluation.grounding_cases import cases
from evaluation.grounding import execute


class GroundingEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def test_frozen_synthetic_cases_have_unique_ids_and_explicit_expectations(self):
        dataset = cases()
        self.assertEqual(len(dataset), 65)
        self.assertEqual(len({case['id'] for case in dataset}), len(dataset))
        self.assertTrue(all(case['expected'] and case['source'] and case['candidate'] for case in dataset))
        self.assertIn('source_conflict', {case['category'] for case in dataset})

    async def test_conflict_and_auditor_failure_replay_use_production_graph(self):
        for case in cases():
            if case['id'] in ('source-conflict', 'review-timeout', 'wrong-source', 'multiple-conclusions',
                             'recommendation-without-direct-quote', 'derived-conclusion', 'local-fact-still-wrong',
                             'local-repair-timeout', 'invalid-auditor-structure', 'no-evidence-conditional-advice',
                             'long-code-and-table', 'scoped-table-intro-and-steps', 'scoped-table-footer-and-steps',
                             'knowledge-with-background', 'knowledge-with-examples', 'supported-fact-missing-reference',
                             'shared-citations-learning-list', 'scope-note-one-uncertain-sentence', 'same-paragraph-conflicting-metric',
                             'do-not-confuse-staleness-with-latency', 'partial-async-is-not-entire-request-async',
                             'idempotency-marker-before-business-window'):
                with self.subTest(case=case['id']):
                    result = await execute(case, 'replay')
                    self.assertTrue(result['assertions_passed'])
                    self.assertEqual(result['metrics']['llm_calls'], 0)


if __name__ == '__main__':
    unittest.main()
