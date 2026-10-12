import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from evaluation.answer_synthesis import SCOPE, assertions_for, execute, run, seeded_state
from evaluation.answer_synthesis_cases import cases


class AnswerSynthesisEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def test_synthetic_cases_are_unique_and_cover_required_behaviors(self):
        dataset = cases()
        self.assertEqual(len(dataset), 7)
        self.assertEqual(len({case['id'] for case in dataset}), len(dataset))
        self.assertTrue(all(case['query'] and case['reply'] and case['sources'] and case['human_review'] for case in dataset))
        self.assertEqual({case['category'] for case in dataset}, {'concept', 'tradeoff', 'deduplication', 'source_error', 'source_scope', 'resource_list'})
        for case in dataset:
            state = seeded_state(case)
            self.assertEqual(state['run_id'], '')
            self.assertEqual(state['history_messages'], [])
            self.assertFalse(state.get('conversation_id'))
            self.assertTrue(all(citation['articleId'] == '' for citation in state['task_results']['retrieve_1']['citations']))

    async def test_replay_runs_actual_main_contract_and_final_gate_without_network(self):
        for case in cases():
            with self.subTest(case=case['id']):
                row = await execute(case, 'replay')
                self.assertEqual(row['scope'], SCOPE)
                self.assertTrue(row['assertions_passed'], row['assertions'])
                self.assertEqual(row['scripted_main_calls'], 1)
                self.assertEqual(row['audit']['review_calls'], 1)
                self.assertEqual(row['metrics']['llm_calls'], 0)
                self.assertEqual(row['blocked_calls'], [])

    async def test_non_answer_decision_is_failed_without_dispatching_action(self):
        from app.graph import main_agent, staged_runtime
        decision = main_agent.MainDecision(action='retrieve', retrieval=main_agent.RetrievalRequest(instruction='合成查询'))
        update = {'main_action': 'retrieve', 'main_decision': decision.model_dump()}
        with patch.object(main_agent, 'main_agent_node', AsyncMock(return_value=update)) as actual_main, \
             patch.object(staged_runtime, 'final_gate', AsyncMock()) as gate:
            row = await execute(cases()[0], 'replay')
        self.assertEqual(actual_main.await_count, 1)
        gate.assert_not_awaited()
        self.assertFalse(row['assertions_passed'])
        self.assertFalse(row['assertions']['answer_selected'])

    def test_smoke_checks_do_not_treat_source_lists_as_always_wrong(self):
        resource = next(case for case in cases() if case['category'] == 'resource_list')
        result = {'main_action': 'answer', 'main_decision': {'action': 'answer'},
            'grounding_audit': {'status': 'verified'}, 'final_reply': resource['reply']}
        self.assertTrue(all(assertions_for(resource, result, []).values()))
        self.assertFalse(assertions_for(resource, result, ['db.execute'])['no_external_action_or_memory_write'])

    async def test_outputs_declare_limited_scope_and_include_reviewable_replies(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / 'synthesis'
            args = SimpleNamespace(mode='replay', ids=['concept-explanation', 'explicit-resource-list'],
                limit=None, timeout=30, output=str(output))
            self.assertEqual(await run(args), 0)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            rows = [json.loads(line) for line in (output / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
            reviews = [json.loads(line) for line in (output / 'reviews.template.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(manifest['scope'], SCOPE)
            self.assertEqual(manifest['live_models'], [])
            self.assertEqual(summary['smoke_assertions_passed'], 2)
            self.assertNotIn('accuracy', summary)
            self.assertIsNone(summary['human_synthesis_quality'])
            self.assertTrue(all(row['candidate_reply'] and row['reply'] for row in rows))
            self.assertTrue(all(row['sources'] and row['human_pass'] is None for row in reviews))

    async def test_unknown_ids_and_unknown_modes_are_rejected(self):
        with TemporaryDirectory() as temporary:
            args = SimpleNamespace(mode='replay', ids=['does-not-exist'], limit=None, timeout=30, output=temporary)
            with self.assertRaisesRegex(ValueError, '未知样例'):
                await run(args)
        with self.assertRaises(ValueError):
            await execute(cases()[0], 'unknown')


if __name__ == '__main__':
    unittest.main()
