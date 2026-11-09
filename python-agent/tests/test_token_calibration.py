"""Measured usage pairs survive resume; missing usage never means zero."""
from types import SimpleNamespace
import unittest
from uuid import uuid4

from langchain_core.messages import HumanMessage
from app.services.run_metrics import RunMetrics
from evaluation.token_calibration import summarize


class CalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pairs_actual_total_input_and_deduplicates_resumed_snapshots(self):
        meter, call = RunMetrics(), uuid4()
        await meter.on_chat_model_start({}, [[HumanMessage(content='中文 example code')]], run_id=call,
            invocation_params={'model': 'fixture-model', 'tools': []})
        response = SimpleNamespace(llm_output={'model_name': 'fixture-model', 'token_usage': {
            'prompt_tokens': 100, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 80}}, generations=[])
        await meter.on_llm_end(response, run_id=call)
        await meter.on_llm_end(response, run_id=call)
        first = meter.snapshot()
        restored = RunMetrics(first).snapshot()
        self.assertEqual(len(first['token_calibration']), 1)
        self.assertEqual(first['token_calibration'][0]['actual_input_tokens'], 100)
        report = summarize(first['token_calibration'] + restored['token_calibration'])
        self.assertEqual(report['groups'][0]['measured_samples'], 1)
        self.assertFalse(report['automatic_budget_adjustment'])
        self.assertEqual(first['input_tokens'], 100)

    async def test_failed_and_missing_usage_are_explicit_unknown_values(self):
        meter = RunMetrics()
        for failed in (False, True):
            call = uuid4()
            await meter.on_chat_model_start({}, [[HumanMessage(content='test')]], run_id=call)
            if failed:
                await meter.on_llm_error(RuntimeError('fixture'), run_id=call)
            else:
                await meter.on_llm_end(SimpleNamespace(llm_output={}, generations=[]), run_id=call)
        rows = meter.snapshot()['token_calibration']
        self.assertEqual({row['status'] for row in rows}, {'failed', 'missing'})
        self.assertTrue(all(row['actual_input_tokens'] is None for row in rows))
        self.assertEqual(summarize(rows)['groups'][0]['missing_or_failed'], 2)
