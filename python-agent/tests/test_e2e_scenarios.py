import json
import tempfile
import unittest
import hashlib
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from evaluation.scenario_data import build_cases
from evaluation.scenarios import (StreamCapture, aggregate_run_metrics, contract_checks,
                                  execute_scenario, request_answer, save_reports, select_cases,
                                  stale_probe_checks, revision_changed, summarize, validate_scenarios)
from evaluation.scenarios import main


class ScenarioTests(unittest.TestCase):
    def test_revision_allows_unchanged_content_but_keeps_hash_and_pending_contract(self):
        before = {'runId': 'r', 'draftHash': 'h', 'title': 'T', 'summary': 'S', 'draft': 'no code'}
        self.assertFalse(revision_changed(before, dict(before)))
        self.assertTrue(revision_changed(before, {**before, 'draft': 'new text', 'draftHash': 'new'}))
        for after in (None, {**before, 'runId': 'other'}, {**before, 'draft': 'new text'},
                      {**before, 'draftHash': 'artificial'}):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                revision_changed(before, after)

    def test_dataset_has_distinct_journeys_and_frozen_relevance(self):
        cases = build_cases()
        validate_scenarios(cases)
        self.assertEqual(len(cases), 136)
        self.assertEqual(len({c['category'] for c in cases}), 13)
        self.assertGreater(sum(len(c['steps']) for c in cases), 170)
        self.assertTrue(any(len(c['steps'][0].get('approval_actions', [])) == 3 for c in cases))
        for c in cases:
            if c['category'] == 'retrieval': self.assertTrue(c['steps'][0]['relevant_documents'])

    def test_stratified_selection_is_repeatable_and_web_opt_in(self):
        cases = build_cases()
        first = select_cases(cases, limit=12, seed=42)
        self.assertEqual(first, select_cases(cases, limit=12, seed=42))
        self.assertEqual(len({c['category'] for c in first}), 12)
        self.assertFalse(any(c.get('requires_web') for c in first))
        self.assertEqual(len(select_cases(cases)), 132)
        self.assertEqual(len(select_cases(cases, include_web=True)), 136)

    def test_invalid_plan_rejected_before_writing(self):
        case = build_cases()[0]
        with self.assertRaises(ValueError): validate_scenarios([case, case])
        with self.assertRaises(ValueError): validate_scenarios([{**case, 'steps': [{'kind': 'chat', 'query': 'q', 'approval_actions': ['approve', 'reject']}]}])
        with self.assertRaises(ValueError): validate_scenarios([{**case, 'steps': [{'kind': 'chat', 'query': 'q' * 16001}]}])

    def test_every_step_required_and_missing_scenarios_stay_in_denominator(self):
        cases = select_cases(build_cases(), limit=2)
        trial = {'case_id': cases[0]['id'], 'repetition': 0, 'contract_passed': False,
                 'total_duration_ms': 800, 'error_type': 'ReadTimeout',
                 'steps': [{'contract_passed': True, 'duration_ms': 200, 'checks': {'x': True}},
                           {'contract_passed': False, 'duration_ms': 600, 'checks': {'citation': False}}]}
        summary = summarize(cases, [trial], 2)
        self.assertEqual(summary['expected_trials'], 4)
        self.assertEqual(summary['automatic_contract_pass_rate'], 0)
        self.assertEqual(summary['token_usage_missing_trials'], 4)
        self.assertEqual(summary['timed_out'], 1)
        self.assertEqual(summary['failed_checks'], {'citation': 1})
        self.assertIsNone(summary['human_task_completion_rate_reviewed_only'])
        with self.assertRaises(ValueError): summarize(cases, [trial, trial], 2)
        with self.assertRaises(ValueError): summarize(cases, [{**trial, 'case_id': 'foreign'}], 2)

    def test_report_pending_review_and_failures_are_separate(self):
        cases = select_cases(build_cases(), categories=['answer'], limit=1)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            summary = save_reports(output, cases, [], {'repeats': 3, 'concurrency': 1, 'seed': 42})
            self.assertEqual(summary['human_review_pending'], 3)
            self.assertEqual(summary['recorded_trials'], 0)
            self.assertIn('非真实用户日志', (output / 'report.md').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((output / 'summary.json').read_text(encoding='utf-8'))['expected_trials'], 3)

    def test_rescore_web_only_frozen_plan_without_current_dataset(self):
        case = next(c for c in build_cases() if c['category'] == 'web')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            frozen = json.dumps(case, ensure_ascii=False) + '\n'
            (output / 'cases.frozen.jsonl').write_text(frozen, encoding='utf-8')
            manifest = {'repeats': 1, 'concurrency': 1, 'seed': 42,
                        'selected_cases_sha256': hashlib.sha256((output / 'cases.frozen.jsonl').read_bytes()).hexdigest()}
            (output / 'summary.json').write_text(json.dumps({'manifest': manifest}), encoding='utf-8')
            (output / 'predictions.jsonl').write_text(json.dumps({'case_id': case['id'], 'repetition': 0,
                'contract_passed': False, 'total_duration_ms': 10, 'steps': []}) + '\n', encoding='utf-8')
            with patch('sys.argv', ['scenarios', 'score', '--cases', str(output / 'missing.jsonl'), '--output', folder]), redirect_stdout(io.StringIO()):
                main()
            summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['categories']['web']['expected_trials'], 1)

    def test_approval_metrics_latest_snapshot_only_and_missing_unknown(self):
        runs = {'a': {'token_usage_complete': True, 'input_tokens': 10, 'output_tokens': 5, 'llm_calls': 1}}
        runs['a'] = {'token_usage_complete': True, 'input_tokens': 30, 'output_tokens': 12, 'llm_calls': 2}
        result = aggregate_run_metrics(runs)
        self.assertEqual(result['input_tokens'], 30)
        self.assertEqual(result['llm_calls'], 2)
        runs['failed'] = None
        result = aggregate_run_metrics(runs)
        self.assertFalse(result['token_usage_complete'])
        self.assertIsNone(result['input_tokens'])

    def test_citations_must_be_used_and_point_to_labelled_article(self):
        step = {'required_citations': True, 'relevant_documents': ['sample_01']}
        answer = {'reply': '说明 [retrieve_1:1]', 'citations': [{'id': 'retrieve_1:1', 'articleId': '42'}]}
        self.assertTrue(all(contract_checks(step, answer, 'succeeded', [], {'sample_01': '42'}).values()))
        checks = contract_checks(step, {**answer, 'reply': '没有使用来源'}, 'succeeded', [], {'sample_01': '42'})
        self.assertFalse(checks['citations_used_in_reply'])
        checks = contract_checks(step, answer, 'succeeded', [], {'sample_01': '43'})
        self.assertFalse(checks['labelled_article_used'])
        checks = contract_checks(step, {**answer, 'reply': '编造 [retrieve_1:99]'}, 'succeeded', [], {'sample_01': '42'})
        self.assertFalse(checks['citation_ids_consistent'])

    def test_masked_conflict_is_not_reported_as_unauthorized_save(self):
        checks = stale_probe_checks(500, 'awaiting_approval', [], set())
        self.assertFalse(checks['stale_approval_conflict_status'])
        self.assertTrue(checks['stale_approval_kept_pending'])
        self.assertTrue(checks['stale_approval_no_save'])
        unsafe = stale_probe_checks(200, 'succeeded', [{'article_id': 42, 'deleted': 0}], set())
        self.assertFalse(unsafe['stale_approval_kept_pending'])
        self.assertFalse(unsafe['stale_approval_no_save'])

    def test_stream_framing_and_verified_answer_order(self):
        capture = StreamCapture()
        frames = ['__CONV_ID__:123', '__RUN_ID__:run',
                  '__ANSWER__:' + json.dumps({'type': 'start'}),
                  '__ANSWER__:' + json.dumps({'type': 'delta', 'seq': 0, 'content': '第一行\n第二行'}),
                  '__ANSWER__:' + json.dumps({'type': 'end', 'chunks': 1})]
        for i, frame in enumerate(frames):
            capture.line('data:' + frame, i * 20)
            capture.line('', i * 20)
        self.assertEqual(capture.result()['reply'], '第一行\n第二行')
        self.assertEqual(capture.first_event_ms, 0)
        self.assertEqual(capture.first_answer_ms, 60)
        with self.assertRaises(ValueError): capture.frame('__ANSWER__:{"type":"delta","seq":1,"content":"late"}', 120)

    def test_stream_failure_and_truncation_not_success(self):
        capture = StreamCapture()
        capture.frame('__CONV_ID__:123', 0)
        capture.frame('__RUN_ID__:run', 1)
        with self.assertRaises(ValueError): capture.result()
        with self.assertRaises(RuntimeError): capture.frame('[ERROR] upstream timeout', 5)

    def test_interrupt_can_finish_stream_without_answer(self):
        capture = StreamCapture()
        capture.frame('__CONV_ID__:123', 0)
        capture.frame('__RUN_ID__:run', 1)
        capture.line('data:__INTERRUPTED__:{"draftHash":"abc"}', 2)
        capture.finish(2)
        self.assertEqual(capture.result()['reply'], '')
        self.assertEqual(capture.pending['draftHash'], 'abc')


class ScenarioFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_masked_conflict_still_verifies_remaining_valid_save(self):
        case = {'id': 'revise', 'category': 'draft', 'review_rubric': 'review', 'steps': [
            {'kind': 'chat', 'query': 'draft', 'approval_actions': ['更短一点', 'approve'], 'stale_approval_probe': True}]}
        saved = {'article_id': 42, 'status': 0, 'deleted': 0}
        async def ledger(database, uid, rid, metrics):
            metrics[rid] = {'token_usage_complete': True, 'input_tokens': 30, 'output_tokens': 10, 'llm_calls': 3}
            return ('awaiting_approval', {}, []) if ledger.calls == 0 else ('succeeded', {'reply': 'saved'}, [])
        ledger.calls = 0
        async def capture(*args):
            value = await ledger(*args)
            ledger.calls += 1
            return value
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, json={'code': 500})
        db = AsyncMock()
        db.fetch_all.return_value = []
        answers = [({'conversationId': '1', 'runId': 'r1', 'reply': ''}, {'draftHash': 'old', 'draft': 'old'}),
                   ({'conversationId': '1', 'runId': 'r1', 'reply': ''}, {'draftHash': 'new', 'draft': 'new'}),
                   ({'conversationId': '1', 'runId': 'r1', 'reply': 'saved', 'draftArticleId': '42'}, None)]
        with patch('evaluation.scenarios.memory_snapshot', return_value={}), \
             patch('evaluation.scenarios.article_snapshot', side_effect=[[], [], [], [saved]]), \
             patch('evaluation.scenarios.capture_sources', return_value=({}, True)), \
             patch('evaluation.scenarios.capture_run', side_effect=capture), \
             patch('evaluation.scenarios.request_answer', side_effect=answers):
            trial = await execute_scenario(case, 0, client, db, 1, {}, 10)
        checks = trial['steps'][0]['checks']
        self.assertFalse(trial['contract_passed'])
        self.assertFalse(checks['stale_approval_conflict_status'])
        self.assertTrue(checks['stale_approval_no_save'])
        self.assertTrue(checks['approved_draft_persisted'])
        self.assertEqual(trial['metrics']['llm_calls'], 3)

    async def test_http_timeout_is_not_a_successful_answer(self):
        async def server(request): raise httpx.ReadTimeout('simulated timeout', request=request)
        async with httpx.AsyncClient(base_url='http://local/api', transport=httpx.MockTransport(server)) as client:
            with self.assertRaises(httpx.ReadTimeout): await request_answer(client, '/agent/chat', {}, 'json', {})

    async def test_partial_sse_identity_survives_error_for_cancellation(self):
        async def server(request):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                text='data:__CONV_ID__:42\n\ndata:__RUN_ID__:run1\n\ndata:[ERROR] upstream failed\n\n')
        record = {}
        async with httpx.AsyncClient(base_url='http://local/api', transport=httpx.MockTransport(server)) as client:
            with self.assertRaises(RuntimeError): await request_answer(client, '/agent/chat', {}, 'sse', record)
        self.assertEqual(record['runId'], 'run1')
        self.assertEqual(record['conversationId'], '42')

    async def test_second_turn_failure_does_not_erase_first_or_pass_whole_scenario(self):
        case = {'id': 'multi-failure', 'category': 'followup', 'review_rubric': 'review',
                'steps': [{'kind': 'chat', 'query': 'first'}, {'kind': 'chat', 'query': 'followup'}]}
        db = AsyncMock()
        db.fetch_all.return_value = []
        async def ledger(database, uid, rid, metrics):
            metrics[rid] = None
            return 'succeeded', {'reply': 'ok'}, []
        with patch('evaluation.scenarios.memory_snapshot', return_value={}), \
             patch('evaluation.scenarios.article_snapshot', return_value=[]), \
             patch('evaluation.scenarios.capture_sources', return_value=({}, True)), \
             patch('evaluation.scenarios.capture_run', side_effect=ledger), \
             patch('evaluation.scenarios.request_answer', side_effect=[({'conversationId': '42', 'runId': 'r1', 'reply': 'ok'}, None), httpx.ReadTimeout('test')]):
            trial = await execute_scenario(case, 0, AsyncMock(), db, 1, {}, 10)
        self.assertFalse(trial['contract_passed'])
        self.assertTrue(trial['steps'][0]['contract_passed'])
        self.assertEqual(trial['steps'][1]['error_type'], 'ReadTimeout')
        self.assertFalse(trial['metrics']['token_usage_complete'])


if __name__ == '__main__': unittest.main()
