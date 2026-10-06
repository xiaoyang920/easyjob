"""Synthetic fixtures and ID binding, without creating users or accessing cloud services."""
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.sample_data import generate
from evaluation.metrics import validate_cases
from evaluation.local_samples import bind_cases, AUTHOR
from evaluation.run import write_report


class SampleDataTests(unittest.TestCase):
    def fixture(self, directory):
        generate(Path(directory))
        read = lambda name: [json.loads(line) for line in (Path(directory) / name).read_text(encoding='utf-8').splitlines()]
        return read('rag.samples.articles.jsonl'), read('rag.samples.cases.jsonl')

    def test_labels_only_reference_existing_corpus_and_keep_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            articles, cases = self.fixture(directory)
            self.assertEqual(len(articles), 24); self.assertEqual(len(cases), 48)
            validate_cases(cases)
            known = {item['id'] for item in articles}
            self.assertEqual(len(known), len(articles))
            for case in cases:
                self.assertEqual(case['annotation_source'], 'synthetic_authored')
                self.assertTrue(set(case['relevance']) <= known)
                self.assertIn(3, case['relevance'].values())
                self.assertTrue(case['label_basis'])

    def test_binding_real_ids_preserves_grades_and_isolates_author(self):
        with tempfile.TemporaryDirectory() as directory:
            articles, cases = self.fixture(directory)
            mapping = {a['id']: {'article_id': str(1000 + i)} for i, a in enumerate(articles)}
            bound = bind_cases(cases, mapping); validate_cases(bound)
            for original, actual in zip(cases, bound):
                self.assertEqual(actual['relevance'], {mapping[key]['article_id']: grade for key, grade in original['relevance'].items()})
                self.assertEqual(actual['filters'], {'author_name': AUTHOR})
                self.assertTrue(all(key.isdigit() for key in actual['relevance']))
                self.assertEqual(actual['annotation_source'], 'synthetic_authored')
            self.assertNotIn('filters', cases[0])

    def test_report_cannot_describe_constructed_labels_as_human_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            _, cases = self.fixture(directory)
            write_report(directory, cases, [], 1, {'mode': 'sample_fixture', 'dataset_sha256': 'fixture',
                                                 'annotation_sources': ['synthetic_authored']})
            report = (Path(directory) / 'report.md').read_text(encoding='utf-8')
            self.assertIn('不代表真实用户查询或独立人工标注效果', report)


if __name__ == '__main__': unittest.main()
