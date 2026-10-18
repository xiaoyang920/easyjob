"""Global thresholds, complete turns, bounded attempts and durable cursors."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import HumanMessage
from app.config import settings
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.services import main_context
from app.services.conversation import ConversationService
from app.utils.context_budget import request_tokens, split_history
from test_context_budget import FakeStore, budgets


def long_history(rounds=12, tokens=4000):
    return [{'message_id': i + 1, 'role': 'user' if i % 2 == 0 else 'assistant', 'content': 'x ' * tokens}
            for i in range(rounds * 2)]


def source_state(tokens=96000, history=None):
    state = create_initial_state(1, '按当前已确认的要求回答', history or [])
    state['task_results'] = {f'source_{i}': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
        'result': 'x ' * (tokens // 2), 'citations': []} for i in range(2)}
    return state


class FullRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='用户已确认：文章面向 Java 初学者。')))
        self.summary_patch = patch('app.services.conversation.get_llm', return_value=self.model)
        self.summary_patch.start()
        self.addCleanup(self.summary_patch.stop)

    async def prepare(self, state):
        return await main_context.prepare_context(state, main_agent.main_message_renderer(state), [main_agent.MainDecision])

    async def test_history_above_32k_with_small_total_is_not_compacted_or_cropped(self):
        history = long_history(5, 4000)
        state = create_initial_state(1, '继续', history)
        prepared, update = await self.prepare(state)
        self.assertEqual(update['context_compaction']['status'], 'below_threshold')
        self.assertGreater(update['context_compaction']['before_tokens'], 32768)
        self.assertEqual(json.loads(main_agent.build_main_messages(prepared)[1].content)['history'], history)
        self.model.ainvoke.assert_not_awaited()

    async def test_large_sources_and_small_history_never_create_a_compaction_loop(self):
        history = long_history(2, 20)
        state = source_state(history=history)
        prepared, update = await self.prepare(state)
        self.assertGreater(update['context_compaction']['before_tokens'], settings.CONTEXT_COMPACT_TRIGGER_TOKENS)
        self.assertEqual(update['context_compaction']['status'], 'insufficient_expected_saving')
        self.assertEqual(prepared['history_messages'], history)
        main_agent.build_main_messages(prepared)
        # Only tool data grows; history is the same version in the next round.
        prepared['main_round'] = 1
        prepared['task_results']['source_0']['result'] += 'x ' * 2000
        _, second = await self.prepare(prepared)
        self.assertEqual(second['context_compaction']['status'], 'already_attempted')
        self.model.ainvoke.assert_not_awaited()

    async def test_real_main_can_answer_above_soft_threshold_without_summary_calls(self):
        state = source_state(history=long_history(2, 20))
        control = SimpleNamespace(ainvoke=AsyncMock(return_value={'action': 'answer', 'reply': '已了解。'}))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        with patch.object(main_agent, 'get_llm', return_value=model):
            result = await main_agent.main_agent_node(state)
        self.assertEqual(result['main_action'], 'answer')
        self.assertEqual(control.ainvoke.await_count, 1)
        self.model.ainvoke.assert_not_awaited()

    async def test_global_trigger_compacts_old_turns_once_and_retains_whole_recent_turns(self):
        state = create_initial_state(1, '请继续', long_history())
        prepared, update = await self.prepare(state)
        stats = update['context_compaction']
        self.assertEqual(stats['status'], 'compacted')
        self.assertGreaterEqual(stats['before_tokens'], settings.CONTEXT_COMPACT_TRIGGER_TOKENS)
        self.assertLess(stats['after_tokens'], settings.CONTEXT_COMPACT_TARGET_TOKENS)
        _, turns = split_history(prepared['history_messages'])
        self.assertEqual(turns, split_history(state['history_messages'])[1][-3:])
        calls = self.model.ainvoke.await_count
        prepared['task_results'] = source_state(75000)['task_results']
        _, again = await self.prepare(prepared)
        self.assertEqual(again['context_compaction']['status'], 'already_attempted')
        self.assertEqual(self.model.ainvoke.await_count, calls)

    async def test_latest_complete_turn_over_24k_is_kept_intact(self):
        history = long_history(9, 4000) + long_history(1, 14000)
        state = create_initial_state(1, '继续', history)
        prepared, update = await self.prepare(state)
        self.assertEqual(update['context_compaction']['status'], 'compacted')
        self.assertEqual(prepared['history_messages'][-2:], history[-2:])
        self.assertEqual(len(prepared['history_messages']), 3)

    async def test_mandatory_data_above_hard_limit_stops_without_any_model(self):
        state = source_state(125000, long_history(2, 20))
        with patch.object(main_agent, 'get_llm') as model:
            result = await main_agent.main_agent_node(state)
        self.assertEqual(result['context_compaction']['status'], 'mandatory_over_budget')
        self.assertIn('处理预算', result['final_reply'])
        model.assert_not_called()
        self.model.ainvoke.assert_not_awaited()

    async def test_failed_summary_is_not_retried_for_same_history_version(self):
        state = create_initial_state(1, '继续', long_history())
        self.model.ainvoke.side_effect = TimeoutError('offline')
        prepared, update = await self.prepare(state)
        self.assertEqual(update['context_compaction']['status'], 'failed')
        self.assertEqual(prepared['history_messages'], state['history_messages'])
        await self.prepare(prepared)
        self.assertEqual(self.model.ainvoke.await_count, 1)

    async def test_no_gain_result_does_not_replace_history_or_loop(self):
        state = create_initial_state(1, '继续', long_history())
        outcome = {'history': state['history_messages'], 'status': 'no_gain', 'summary_calls': 1}
        with patch.object(main_context.context_service, 'compact_history', AsyncMock(return_value=outcome)) as compact:
            prepared, update = await self.prepare(state)
            self.assertEqual(update['context_compaction']['status'], 'no_gain')
            await self.prepare(prepared)
            self.assertEqual(compact.await_count, 1)

    async def test_failure_above_hard_limit_stops_without_discarding_history(self):
        state = create_initial_state(1, '继续', long_history(16))
        self.model.ainvoke.side_effect = TimeoutError('offline')
        with patch.object(main_agent, 'get_llm') as model:
            result = await main_agent.main_agent_node(state)
        self.assertEqual(result['context_compaction']['status'], 'failed')
        self.assertEqual(result['context_compaction']['summary_calls'], 1)
        self.assertIn('处理预算', result['final_reply'])
        self.assertNotIn('history_messages', result)
        model.assert_not_called()

    async def test_schema_and_fixed_instructions_count_toward_the_trigger(self):
        state = create_initial_state(1, '继续', long_history(3, 1000))
        render = main_agent.main_message_renderer(state)
        without = request_tokens(render(state['history_messages']))
        with_schema = request_tokens(render(state['history_messages']), [main_agent.MainDecision])
        self.assertGreater(with_schema, without)
        with budgets(CONTEXT_COMPACT_TRIGGER_TOKENS=(without + with_schema) // 2,
                     CONTEXT_COMPACT_TARGET_TOKENS=7000, HISTORY_RECENT_TOKENS=2000,
                     SUMMARY_MAX_TOKENS=128, CONTEXT_COMPACT_MIN_SAVING_TOKENS=256):
            _, update = await self.prepare(state)
        self.assertEqual(update['context_compaction']['status'], 'compacted')


class DurableHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = ConversationService.__new__(ConversationService)
        self.service._redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(), delete=AsyncMock())
        self.model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='用户已确认的结论。')))
        self.database = FakeStore(long_history(2, 500))

    async def snapshot(self):
        return await self.service._load_context(1)

    async def compact(self, prefix=2, **kwargs):
        return await self.service.compact_history(1, await self.snapshot(), prefix, **kwargs)

    async def test_load_and_postprocess_do_not_call_llm_or_enforce_32k(self):
        database = FakeStore(long_history(5, 4000))
        with patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm') as model:
            history = await self.service.get_context_for_llm(1)
            await self.service.postprocess_messages(1)
        self.assertEqual(len(history), 10)
        self.assertIn('full:v4', self.service._llm_cache_key(1))
        model.assert_not_called()

    async def test_cursor_advances_only_complete_old_turn_and_raw_rows_remain(self):
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm', return_value=self.model):
            result = await self.compact(user_id=1)
        self.assertEqual(result['status'], 'compacted')
        self.assertEqual(self.database.cursor, 2)
        self.assertEqual(result['history'][1:], self.database.history[2:])
        self.assertEqual(len(self.database.history), 4)
        self.assertIn('old_cursor', self.database.updates[0][1])

    async def test_current_question_appended_after_snapshot_is_never_summarized(self):
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm', return_value=self.model):
            history = await self.snapshot()
            self.database.history.append({'message_id': 5, 'role': 'user', 'content': 'CURRENT_UNIQUE_QUESTION'})
            await self.service.compact_history(1, history, 2)
        self.assertNotIn('CURRENT_UNIQUE_QUESTION', self.model.ainvoke.call_args.args[0][0].content)
        self.assertEqual(self.database.cursor, 2)

    async def test_no_gain_does_not_write_summary_or_advance_cursor(self):
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm', return_value=self.model):
            result = await self.compact(accept=lambda history: False)
        self.assertEqual(result['status'], 'no_gain')
        self.database.execute.assert_not_awaited()

    async def test_stale_summary_is_not_committed_or_injected(self):
        async def concurrent(messages):
            self.database.summary, self.database.cursor = '其他调用已更新', 3
            return SimpleNamespace(content='当前调用过时摘要')
        self.model.ainvoke.side_effect = concurrent
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm', return_value=self.model):
            history = await self.snapshot()
            result = await self.service.compact_history(1, history, 2)
        self.assertEqual(result['status'], 'stale')
        self.assertIs(result['history'], history)
        self.database.execute.assert_not_awaited()

    async def test_cas_race_after_precheck_cannot_replace_active_history(self):
        original_execute = self.database.execute.side_effect
        async def race(sql, params):
            self.database.summary, self.database.cursor = '更新后的摘要', 3
            await original_execute(sql, params)
        self.database.execute.side_effect = race
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm', return_value=self.model):
            history = await self.snapshot()
            result = await self.service.compact_history(1, history, 2)
        self.assertEqual(result['status'], 'stale')
        self.assertIs(result['history'], history)
        self.assertEqual(self.database.cursor, 3)

    async def test_long_turn_batching_and_call_cap_never_commit_partial_turn(self):
        database = FakeStore([{'message_id': 1, 'role': 'user', 'content': 'x ' * 4000},
                              *long_history(1, 5)])
        # Assign unique chronological IDs to the latest retained turn.
        database.history[1]['message_id'], database.history[2]['message_id'] = 2, 3
        with budgets(SUMMARY_INPUT_MAX_TOKENS=1800, SUMMARY_MAX_TOKENS=128), \
             patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm', return_value=self.model):
            result = await self.service.compact_history(1, await self.snapshot(), 1)
        self.assertEqual(result['status'], 'compacted')
        self.assertEqual(database.cursor, 1)
        self.assertGreater(self.model.ainvoke.await_count, 1)
        self.assertTrue(all(request_tokens(call.args[0]) <= 1800 for call in self.model.ainvoke.call_args_list))
        database = FakeStore(database.history)
        self.model.ainvoke.reset_mock()
        with budgets(SUMMARY_INPUT_MAX_TOKENS=1800, SUMMARY_MAX_TOKENS=128, SUMMARY_MAX_CALLS=1), \
             patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm', return_value=self.model):
            result = await self.service.compact_history(1, await self.snapshot(), 1)
        self.assertEqual(result['status'], 'call_limit')
        self.model.ainvoke.assert_not_awaited()
        database.execute.assert_not_awaited()

    async def test_empty_summary_timeout_and_lost_fence_do_not_write(self):
        import asyncio
        for failure in ('empty', 'timeout', 'fence'):
            self.database = FakeStore(long_history(2, 500))
            self.model.ainvoke.side_effect = None
            self.model.ainvoke.return_value = SimpleNamespace(content='' if failure == 'empty' else '摘要')
            async def slow(messages):
                await asyncio.sleep(1)
            if failure == 'timeout':
                self.model.ainvoke.side_effect = slow
            fence = AsyncMock(side_effect=RuntimeError('lost lease')) if failure == 'fence' else None
            with budgets(SUMMARY_TIMEOUT_SECONDS=0.01), patch('app.services.conversation.db', self.database), \
                 patch('app.services.conversation.get_llm', return_value=self.model):
                with self.assertRaises((ValueError, TimeoutError, RuntimeError)):
                    await self.compact(before_commit=fence)
            self.database.execute.assert_not_awaited()

    async def test_split_turn_boundary_is_rejected_before_model_call(self):
        with patch('app.services.conversation.db', self.database), patch('app.services.conversation.get_llm') as model:
            with self.assertRaises(ValueError):
                await self.compact(prefix=1)
        model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
