import json
from pathlib import Path
import tempfile
import unittest
from evaluation.delivery_quality import digest,write_jsonl
from evaluation.review_workbench import build,bundle,compare

class ReviewWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.cases=[{'id':'a','category':'specific_facts','query':'测试问题','sources':[{'content':'</script><script>alert(1)</script>'}]}]
        self.rows=[{'id':'a','candidate_reply':'候选','reply':'最终','duration_ms':100}]
        write_jsonl(self.root/'cases.jsonl',self.cases);write_jsonl(self.root/'trials.jsonl',self.rows)
        (self.root/'manifest.json').write_text(json.dumps({'mode':'live','expected_trials':2,'dataset_hash':digest(self.cases),'trials_hash':digest(self.rows)}),encoding='utf-8')
    def review(self,name='first',completed=True):
        return {'id':'a','assessor':'human','reviewer':name,'candidate_hash':digest('候选'),'final_hash':digest('最终'),
                'task_completed':completed,'context_coherent':True,'candidate_correct_units':2,'falsely_blocked_units':0,'specific_facts':1,'unsupported_specific_facts':0}
    def test_workbench_escapes_source_markup_and_contains_no_remote_dependencies(self):
        html=build(self.root,self.root/'review.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert(1)</script>',html)
        self.assertIn('\\u003c/script\\u003e',html);self.assertIn("connect-src 'none'",html)
        self.assertEqual(bundle(self.root)['expected'],2)
    def test_mutated_outputs_and_overwrites_are_rejected(self):
        build(self.root,self.root/'review.html')
        with self.assertRaises(ValueError):build(self.root,self.root/'review.html')
        write_jsonl(self.root/'trials.jsonl',[{**self.rows[0],'reply':'changed'}])
        with self.assertRaises(ValueError):bundle(self.root)
    def test_disagreements_are_reported_without_automatic_labels(self):
        write_jsonl(self.root/'a.jsonl',[self.review()]);write_jsonl(self.root/'b.jsonl',[self.review('second',False)])
        result=compare(self.root,self.root/'a.jsonl',self.root/'b.jsonl')
        self.assertEqual(result['overlap'],1)
        self.assertEqual(result['disagreements'][0]['fields'],{'task_completed':[True,False]})
