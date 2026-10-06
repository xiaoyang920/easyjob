"""Expanded benchmark labels and scorer regressions; no model calls."""
import unittest
from collections import Counter

from evaluation.expanded_routes import build_cases
from evaluation.metrics import summarize, validate_cases


class ExpandedRouteTests(unittest.TestCase):
    def test_frozen_cases_cover_nine_groups_without_duplicate_queries(self):
        cases = build_cases()
        validate_cases(cases)
        self.assertEqual(len(cases), 144)
        self.assertEqual(len({case['query'] for case in cases}), 144)
        self.assertEqual(set(Counter(case['category'] for case in cases).values()), {16})
        self.assertEqual(sum(case.get('requires_behavior_review', False) for case in cases), 64)
        self.assertTrue(all(case['annotation_source'] == 'product_rules' for case in cases))

    def cases(self):
        return [{'id': 'a', 'kind': 'route', 'query': '只查本站', 'reviewed': True, 'category': 'web',
                 'requires_behavior_review': True,
                 'acceptable_routes': [{'action': 'retrieve', 'target': 'knowledge', 'allow_web': False}]},
                {'id': 'b', 'kind': 'route', 'query': '解释即可', 'reviewed': True, 'category': 'simple',
                 'acceptable_routes': [{'action': 'answer'}]}]

    def record(self, **extra):
        return {'case_id': 'a', 'variant': 'main', 'repetition': 0, 'status': 'ok', 'latency_ms': 1,
                'action': 'retrieve', 'target': 'knowledge', 'allow_web': False, **extra}

    def test_wrong_web_flag_and_missing_repetitions_reduce_category_score(self):
        report = summarize(self.cases(), [self.record(allow_web=True)], repeats=2)['reports'][0]
        self.assertEqual(report['quality']['route_accuracy'], 0)
        self.assertEqual(report['missing_trials'], 3)
        by_category = {item['category']: item for item in report['categories']}
        self.assertEqual(by_category['web']['expected_trials'], 2)
        self.assertEqual(len(report['mismatches']), 4)

    def test_correct_route_never_automatically_passes_semantic_review(self):
        report = summarize(self.cases(), [self.record()])['reports'][0]
        self.assertEqual(report['quality']['route_accuracy'], 0.5)
        review = report['behavior_reviews']['human']
        self.assertEqual(review['pending_trials'], 1)
        self.assertIsNone(review['pass_rate_reviewed_only'])

    def test_model_review_is_separate_and_failed_requests_cannot_be_reviewed_as_success(self):
        report = summarize(self.cases(), [self.record(behavior_review={'assessor': 'llm', 'passed': True})])['reports'][0]
        self.assertEqual(report['behavior_reviews']['human']['reviewed_trials'], 0)
        self.assertEqual(report['behavior_reviews']['llm']['reviewed_trials'], 1)
        report = summarize(self.cases(), [self.record(status='error', behavior_review={'assessor': 'human', 'passed': True})])['reports'][0]
        self.assertEqual(report['behavior_reviews']['human']['reviewed_trials'], 0)

    def test_invalid_web_labels_are_rejected_before_measurement(self):
        for route in ({'action': 'answer', 'allow_web': False},
                      {'action': 'retrieve', 'target': 'knowledge', 'allow_web': 'false'},
                      {'action': 'retrieve', 'target': 'memory', 'allow_web': True},
                      {'action': 'retrieve', 'allow_website': False}):
            cases = self.cases()
            cases[0]['acceptable_routes'] = [route]
            with self.assertRaises(ValueError):
                validate_cases(cases)


if __name__ == '__main__':
    unittest.main()
