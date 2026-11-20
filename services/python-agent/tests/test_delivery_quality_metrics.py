import unittest
import asyncio
from evaluation.delivery_cases import cases
from evaluation.delivery_quality import digest, summarize


class DeliveryQualityMetricsTests(unittest.TestCase):
    def test_seeded_context_supports_both_direct_answers_and_retrieved_sources(self):
        from evaluation.answer_synthesis import seeded_state
        for case in cases():
            state = seeded_state(case)
            self.assertEqual(state['user_message'], case['query'])
            self.assertEqual(bool(state.get('task_results')), bool(case['sources']))
    def test_direct_answer_replay_executes_without_retrieval_artifacts(self):
        from evaluation.answer_synthesis import execute
        result = asyncio.run(execute(cases()[0], 'replay'))
        self.assertTrue(result['reply'])
        self.assertEqual(result['blocked_calls'], [])
    def row(self):
        return {'id': 'a', 'candidate_reply': 'correct candidate', 'reply': 'partial final', 'duration_ms': 100,
            'metrics': {'llm_calls': 2, 'token_usage_complete': True, 'input_tokens': 100, 'output_tokens': 30}}

    def review(self):
        row = self.row()
        return {'id': 'a', 'assessor': 'human', 'reviewer': 'reviewer-1',
            'candidate_hash': digest(row['candidate_reply']), 'final_hash': digest(row['reply']),
            'task_completed': False, 'context_coherent': True, 'candidate_correct_units': 4,
            'falsely_blocked_units': 1, 'specific_facts': 2, 'unsupported_specific_facts': 1}

    def test_no_labels_never_become_accuracy_and_missing_runs_remain_visible(self):
        report = summarize([self.row()], [], 3, 'live')
        self.assertIsNone(report['task_completion_rate_reviewed_only'])
        self.assertIsNone(report['false_block_rate_reviewed_only'])
        self.assertEqual(report['missing_trials'], 2);self.assertEqual(report['human_review_pending'], 3)
        self.assertEqual(report['automatic_delivery_contract_passed_trials'], 0)
    def test_collection_is_not_misreported_as_successful_delivery(self):
        failed = {**self.row(), 'main_decision': {}, 'audit': {}}
        passed = {**self.row(), 'id': 'b', 'main_decision': {'action': 'answer'},
            'audit': {'status': 'not_required'}, 'assertions': {'not_contract_stop': True}}
        report = summarize([failed, passed], [], 2, 'live')
        self.assertEqual(report['automatic_delivery_contract_passed_trials'], 1)
        self.assertEqual(report['automatic_delivery_contract_failed_or_missing_trials'], 1)

    def test_human_false_block_rate_uses_correct_candidate_units_not_all_text(self):
        report = summarize([self.row()], [self.review()], 1, 'live')
        self.assertEqual(report['false_block_rate_reviewed_only'], .25)
        self.assertEqual(report['unsupported_specific_fact_rate_reviewed_only'], .5)
        self.assertEqual(report['task_completion_rate_reviewed_only'], 0)
        self.assertEqual(report['input_tokens_measured'], 100)

    def test_replay_outputs_cannot_be_scored_as_real_answer_quality(self):
        with self.assertRaises(ValueError): summarize([self.row()], [self.review()], 1, 'replay')

    def test_unknown_duplicate_stale_and_invalid_reviews_are_rejected(self):
        for field, value in [('id', 'unknown'), ('candidate_hash', 'stale'), ('assessor', 'llm'),
                             ('falsely_blocked_units', 5), ('unsupported_specific_facts', -1)]:
            review = {**self.review(), field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                summarize([self.row()], [review], 1, 'live')
        with self.assertRaises(ValueError): summarize([self.row()], [self.review(), self.review()], 1, 'live')

    def test_missing_tokens_remain_unknown(self):
        report = summarize([{**self.row(), 'metrics': {'token_usage_complete': False}}], [], 1, 'live')
        self.assertIsNone(report['input_tokens_measured']);self.assertEqual(report['tokens_measured_trials'], 0)

    def test_dataset_balanced_distinct_and_explicitly_not_a_production_holdout(self):
        rows = cases();self.assertEqual(len(rows), 64);self.assertEqual(len({r['query'] for r in rows}), 64)
        self.assertEqual(len({r['category'] for r in rows}), 8)
        self.assertTrue(all(r['annotation_source'] in ('conversation_derived_technical_question', 'authored_edge_case') for r in rows))
