"""Context integrity and bounded requests, without external services."""
import json
import asyncio
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['LANGFUSE_PUBLIC_KEY'] = ''
os.environ['LANGFUSE_SECRET_KEY'] = ''
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import HumanMessage
from app.config import settings
from app.graph.state_factory import create_initial_state
from app.utils.token_utils import count_tokens, truncate_to_token_budget
from app.utils.context_budget import (ContextBudgetExceeded, messages_tokens, request_tokens,
    input_budget, ensure_request_budget, select_history, text_chunks)
from app.services.conversation import ConversationService
from app.graph import main_agent
from app.services.query_rewrite import QueryRewriteService


def budgets(**overrides):
    stack = ExitStack()
    for name, value in overrides.items():
        stack.enter_context(patch.object(settings, name, value))
    return stack


class WindowTests(unittest.TestCase):
    def test_long_request_beyond_old_character_limit_is_accepted_intact(self):
        query = 'technical detail ' * 6500
        self.assertGreater(len(query), 96000)
        state = create_initial_state(1, query, [])
        messages = main_agent.build_main_messages(state)
        self.assertEqual(messages[-1].content, query)
        self.assertLess(request_tokens(messages, [main_agent.MainDecision]), input_budget())

    def test_long_main_answer_and_citation_patch_share_the_expanded_schema(self):
        text = 'explanation ' * 2500
        self.assertGreater(len(text), 16000)
        self.assertLess(count_tokens(text), settings.MAIN_OUTPUT_MAX_TOKENS)
        self.assertEqual(main_agent.MainDecision(action='answer', reply=text).reply, text)
        self.assertEqual(main_agent.CitationRepair(reply=text).reply, text)
        self.assertEqual(main_agent.MainArtifact(task_id='note', instruction='compare', result=text).result, text)
        self.assertEqual(main_agent.ArtifactCitationRepair(task_id='note', result=text).result, text)

    def test_dependency_beyond_old_character_limit_is_preserved_and_token_bounded(self):
        from app.graph.staged_runtime import dependency_text
        dependencies = {'source': {'result': 'technical ' * 6000}}
        encoded = dependency_text(dependencies)
        self.assertGreater(len(encoded), 48000)
        self.assertEqual(json.loads(encoded), dependencies)
        with budgets(MAIN_CONTEXT_MAX_TOKENS=6000, WORKER_OUTPUT_MAX_TOKENS=1000, CONTEXT_SAFETY_TOKENS=1000):
            with self.assertRaises(ContextBudgetExceeded):
                dependency_text({'source': {'result': 'x ' * 4500}})
        with budgets(DEPENDENCY_MAX_CHARS=100):
            with self.assertRaises(ContextBudgetExceeded):
                dependency_text(dependencies)

    def test_search_input_and_generated_output_use_different_task_budgets(self):
        from app.graph.staged_plan import ExecutionTask
        from app.graph.staged_runtime import task_context, task_result
        parent = create_initial_state(1, 'compare', [])
        long_text = 'data ' * 18000
        source = task_context(parent, ExecutionTask(task_id='source', kind='search', actor='main', instruction='find'))
        update = {'worker_results': [{'result': long_text}]}
        self.assertGreater(count_tokens(long_text), settings.WORKER_OUTPUT_MAX_TOKENS)
        self.assertEqual(task_result(source, update, raw_retrieval=True)['result'], long_text)
        analysis = task_context(parent, ExecutionTask(task_id='analysis', kind='analysis', actor='main', instruction='compare'))
        with self.assertRaisesRegex(ValueError, '输出超出预算'):
            task_result(analysis, update)
        shorter = 'technical ' * 2000
        self.assertEqual(task_result(analysis, {'worker_results': [{'result': shorter}]})['result'], shorter)
        with budgets(TASK_RESULT_MAX_CHARS=100):
            with self.assertRaisesRegex(ValueError, '输出超出预算'):
                task_result(source, update, raw_retrieval=True)

    def test_short_history_keeps_more_than_ten_messages_and_its_summary(self):
        summary = {'role': 'system', 'kind': 'history_summary', 'content': '[之前的对话摘要] 确定给初学者看。'}
        history = [summary, *[{'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)} for i in range(24)]]
        state = create_initial_state(1, '继续说明', history)
        messages = main_agent.build_main_messages(state)
        context = json.loads(messages[1].content)
        self.assertEqual(context['history_summary'], [summary])
        self.assertEqual(context['history'], history[1:])
        self.assertLessEqual(request_tokens(messages, [main_agent.MainDecision]), input_budget())
        rewritten = json.loads(QueryRewriteService._build_history_text(history))
        self.assertEqual(rewritten['history'], history)

    def test_recent_window_never_splits_a_user_assistant_pair(self):
        fixed = {'role': 'system', 'content': 'summary'}
        old = [{'role': 'user', 'content': 'old question'}, {'role': 'assistant', 'content': 'x ' * 200}]
        latest = [{'role': 'user', 'content': 'latest question'}, {'role': 'assistant', 'content': 'latest answer'}]
        window = select_history([fixed, *old, *latest], messages_tokens([fixed, *latest]))
        self.assertEqual(window.messages, [fixed, *latest])
        self.assertEqual(window.omitted_messages, 2)

    def test_long_turn_does_not_get_replaced_by_older_irrelevant_turns(self):
        history = [{'role': 'user', 'content': 'old'}, {'role': 'assistant', 'content': 'answer'},
                   {'role': 'user', 'content': 'x ' * 1000}]
        window = select_history(history, 200)
        self.assertEqual(window.messages, [])
        self.assertEqual(window.omitted_messages, 3)

    def test_whole_request_includes_schema_output_reserve_and_tool_calls(self):
        messages = [HumanMessage(content='你好')]
        with budgets(MAIN_CONTEXT_MAX_TOKENS=1500, MAIN_OUTPUT_MAX_TOKENS=600, CONTEXT_SAFETY_TOKENS=400):
            self.assertEqual(input_budget(), 500)
            ensure_request_budget(messages)
            self.assertGreater(request_tokens(messages, [main_agent.MainDecision]), 500)
            with self.assertRaises(ContextBudgetExceeded):
                ensure_request_budget(messages, [main_agent.MainDecision])
        plain = {'role': 'assistant', 'content': ''}
        tool = {**plain, 'tool_calls': [{'name': 'search', 'args': {'query': 'x ' * 1000}, 'id': 'call'}]}
        self.assertGreater(request_tokens([tool]), request_tokens([plain]) + 500)

    def test_unicode_chunks_and_truncation_preserve_valid_source_prefixes(self):
        text = '中文🧑🏽‍💻\n<|endoftext|>代码 ' * 100
        chunks = list(text_chunks(text, 80))
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(count_tokens(chunk) <= 80 for chunk in chunks))
        for limit in range(20):
            truncated = truncate_to_token_budget(text, limit)
            self.assertTrue(text.startswith(truncated))
            self.assertNotIn('\ufffd', truncated)
            self.assertLessEqual(count_tokens(truncated), limit)


class MainBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_reclaims_history_budget_before_dropping_necessary_context(self):
        history = [{'role': 'system', 'content': '[之前的对话摘要] 文章确定面向初学者。'}]
        for i in range(8):
            history.extend([{'role': 'user', 'content': f'问题{i} ' * 100},
                            {'role': 'assistant', 'content': f'答复{i} ' * 100}])
        state = create_initial_state(1, '请按已确认的要求继续', history)
        state['active_constraints'] = [{'id': '1', 'key': 'web_search', 'value': 'deny'}]
        overhead = request_tokens(main_agent.build_main_messages({**state, 'history_messages': []}), [main_agent.MainDecision])
        with budgets(MAIN_CONTEXT_MAX_TOKENS=overhead+1800+4096+2048, MAIN_OUTPUT_MAX_TOKENS=4096, CONTEXT_SAFETY_TOKENS=2048):
            messages = main_agent.build_main_messages(state)
            self.assertLessEqual(request_tokens(messages, [main_agent.MainDecision]), input_budget())
        context = json.loads(messages[1].content)
        self.assertEqual(context['history_summary'], history[:1])
        self.assertLess(len(context['history']), len(history) - 1)
        self.assertEqual(context['history'][-2:], history[-2:])
        self.assertEqual(context['active_constraints'], state['active_constraints'])
        self.assertEqual(messages[-1].content, state['user_message'])

    async def test_validation_retry_is_counted_against_the_same_total_budget(self):
        state = create_initial_state(1, '你好', [])
        initial = request_tokens(main_agent.build_main_messages(state), [main_agent.MainDecision])
        control = SimpleNamespace(ainvoke=AsyncMock(return_value={'action': 'invalid'}))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        with budgets(MAIN_CONTEXT_MAX_TOKENS=initial + settings.MAIN_OUTPUT_MAX_TOKENS + settings.CONTEXT_SAFETY_TOKENS + 10), \
             patch.object(main_agent, 'get_llm', return_value=model):
            result = await main_agent.main_agent_node(state)
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertIn('处理预算', result['final_reply'])

    async def test_retrieval_handoff_preserves_summary_before_query_rewrite(self):
        from app.graph import action_runtime
        history = [{'role': 'system', 'content': '[之前的对话摘要] 缓存一致性'}]
        history += [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)} for i in range(24)]
        state = create_initial_state(1, '找资料', history)
        state.update(main_action='retrieve', plan={'tasks': [{'task_id': 'lookup', 'kind': 'search', 'actor': 'main',
                                                           'instruction': '查资料', 'requires_evidence': False}]})
        retrieve = AsyncMock(return_value={'status': 'succeeded', 'result': '找到资料', 'citations': [], 'article_cards': []})
        with patch.object(action_runtime, 'retrieve_evidence', retrieve), \
             patch.object(action_runtime.runtime, 'assert_run', AsyncMock()), patch.object(action_runtime, 'activity', AsyncMock()):
            await action_runtime.main_retrieve_node(state)
        self.assertEqual(retrieve.call_args.args[0]['history_messages'], history)

    async def test_worker_counts_bound_tool_schema_before_a_model_call(self):
        from langchain_core.tools import StructuredTool
        from app.graph.tool_executor import run_tool_agent
        from app.services.tool_recovery import ToolPolicy
        tool = StructuredTool.from_function(lambda query: query, name='search', description='description ' * 1600)
        model = SimpleNamespace(bind_tools=Mock(), ainvoke=AsyncMock())
        model.bind_tools.return_value = model
        with budgets(MAIN_CONTEXT_MAX_TOKENS=4000, WORKER_OUTPUT_MAX_TOKENS=2000, CONTEXT_SAFETY_TOKENS=1000), \
             patch('app.graph.tool_executor.get_llm', return_value=model):
            with self.assertRaises(ContextBudgetExceeded):
                await run_tool_agent('system', 'query', tools=[tool], tool_policies={'search': ToolPolicy(True)})
        model.ainvoke.assert_not_awaited()

    async def test_large_latest_question_stops_before_call_and_is_not_truncated(self):
        query = 'x ' * 150000
        state = create_initial_state(1, query, [])
        with patch.object(main_agent, 'get_llm') as model:
            result = await main_agent.main_agent_node(state)
        model.assert_not_called()
        self.assertIn('处理预算', result['final_reply'])
        self.assertEqual(state['user_message'], query)

    async def test_full_evidence_is_preserved_and_stops_instead_of_silently_truncating(self):
        state = create_initial_state(1, '回答', [])
        state['task_results'] = {'source': {'status': 'succeeded', 'result': 'x ' * 150000,
            'kind': 'search', 'actor': 'main', 'citations': []}}
        with patch.object(main_agent, 'get_llm') as model:
            result = await main_agent.main_agent_node(state)
        model.assert_not_called()
        self.assertIn('处理预算', result['final_reply'])
        self.assertEqual(state['task_results']['source']['result'], 'x ' * 150000)


class FakeStore:
    def __init__(self, history, summary=None, cursor=None):
        self.history = history
        self.summary, self.cursor = summary, cursor
        self.updates = []
        self.fetch_one = AsyncMock(side_effect=self._one)
        self.fetch_all = AsyncMock(side_effect=self._all)
        self.execute = AsyncMock(side_effect=self._execute)

    async def _one(self, sql, params):
        return SimpleNamespace(_mapping={'summary': self.summary, 'summary_upto_msg_id': self.cursor})

    async def _all(self, sql, params):
        return [SimpleNamespace(_mapping={'image_paths': None, **message}) for message in self.history if message['message_id'] > (params.get('cursor') or 0)]

    async def _execute(self, sql, params):
        self.updates.append((sql, params.copy()))
        if self.cursor == params['old_cursor'] and self.summary == params['old_summary']:
            self.summary, self.cursor = params['s'], params['cursor']


if __name__ == '__main__':
    unittest.main()
