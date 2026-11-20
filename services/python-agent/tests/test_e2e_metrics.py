import unittest
import asyncio
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4
from app.services.run_metrics import RunMetrics
from evaluation.e2e import score, validate_review


class E2EMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_subagents_preserve_parent_meter_when_adding_local_tracing(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatResult, ChatGeneration
        from langchain_core.runnables import RunnableLambda
        from app.graph import tool_executor
        class Model(BaseChatModel):
            @property
            def _llm_type(self): return 'offline-meter-fixture'
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content='offline analysis',
                    usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}))])
        meter = RunMetrics()
        async def worker(_):
            return await asyncio.gather(*[tool_executor.run_tool_agent('analyze', 'data', tools=[]) for _ in range(2)])
        with patch.object(tool_executor, 'get_llm', return_value=Model()), patch.object(tool_executor, 'get_langfuse_callback', return_value=None):
            await RunnableLambda(worker).ainvoke({}, config={'callbacks': [meter]})
        snapshot = meter.snapshot()
        self.assertEqual((snapshot['llm_calls'], snapshot['input_tokens'], snapshot['output_tokens']), (2, 20, 4))
        self.assertTrue(snapshot['token_usage_complete'])

    async def test_real_usage_aggregates_across_approval_without_double_count(self):
        meter = RunMetrics()
        rid = uuid4()
        response = SimpleNamespace(llm_output={'token_usage': {'prompt_tokens': 100, 'completion_tokens': 20}}, generations=[])
        await meter.on_chat_model_start({}, [], run_id=rid)
        await meter.on_llm_end(response, run_id=rid)
        await meter.on_llm_end(response, run_id=rid)
        first = meter.snapshot()
        resume = RunMetrics(first)
        await resume.on_llm_end(response, run_id=uuid4())
        result = resume.snapshot()
        self.assertEqual((result['llm_calls'], result['input_tokens'], result['output_tokens']), (2, 200, 40))
        self.assertTrue(result['token_usage_complete'])

    async def test_missing_or_failed_call_usage_is_unknown_not_zero(self):
        meter = RunMetrics()
        await meter.on_chat_model_start({}, [], run_id=uuid4())
        snapshot = meter.snapshot()
        self.assertFalse(snapshot['token_usage_complete'])
        self.assertIsNone(snapshot['input_tokens'])

    def test_failures_and_missing_trials_stay_in_denominator(self):
        trials = [{'contract_passed': True, 'total_duration_ms': 100, 'metrics': {'token_usage_complete': True, 'input_tokens': 50, 'output_tokens': 10}},
                  {'contract_passed': False, 'total_duration_ms': 500}]
        result = score(trials, 4)
        self.assertEqual(result['automatic_contract_pass_rate'], .25)
        self.assertEqual(result['token_usage_missing_trials'], 3)
        self.assertIsNone(result['human_task_completion_rate_reviewed_only'])
        self.assertIsNone(result['human_citation_support_rate_reviewed_only'])
        self.assertEqual(result['total_latency_p95_ms_all_recorded'], 480)

    def test_citation_support_requires_separate_human_judgement(self):
        review = {'assessor': 'human', 'task_completed': False, 'supported_claims': 1, 'total_claims': 2}
        validate_review(review)
        result = score([{'contract_passed': True, 'total_duration_ms': 100, 'review': review}], 1)
        self.assertEqual(result['human_citation_support_rate_reviewed_only'], .5)
        self.assertEqual(result['human_task_completion_rate_reviewed_only'], 0)
        with self.assertRaises(ValueError): validate_review({**review, 'supported_claims': 3})
