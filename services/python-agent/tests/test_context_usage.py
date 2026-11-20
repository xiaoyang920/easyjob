import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from app.config import settings
from app.services.context_usage import context_usage, measured_context_usage, conversation_context_usage
from app.services.run_metrics import RunMetrics
from app.services.run_repository import RunRepository


class ContextUsageTests(unittest.IsolatedAsyncioTestCase):
    def test_unknown_is_not_zero_and_only_numeric_summary_is_public(self):
        unknown = context_usage()
        self.assertIsNone(unknown['usedTokens'])
        self.assertEqual(unknown['limitTokens'], settings.MAIN_CONTEXT_MAX_TOKENS)
        self.assertEqual(unknown['inputBudgetTokens'], settings.MAIN_CONTEXT_MAX_TOKENS -
                         settings.MAIN_OUTPUT_MAX_TOKENS - settings.CONTEXT_SAFETY_TOKENS)
        for raw in ('bad json', 'null', {'total_tokens': True}, {'total_tokens': -1}):
            self.assertIsNone(context_usage(raw)['usedTokens'])
        value = context_usage({'total_tokens': 123, 'prompt': 'private', 'history': 'private'})
        self.assertEqual(value['usedTokens'], 123)
        self.assertNotIn('private', json.dumps(value))

    async def test_metric_persists_request_window_not_cumulative_usage(self):
        persist = AsyncMock()
        meter = RunMetrics({'measured_input_tokens': 5000}, persist=persist)
        window = measured_context_usage({'total_tokens': 1234})
        window['limitTokens'] = 131072
        await meter.on_chat_model_start({}, [], run_id=uuid4(), metadata={
            'context_usage': {'total_tokens': 1234, 'prompt': 'private'},
            'context_window': window, 'context_round': 2})
        saved = persist.call_args.args[0]['context_views'][-1]
        restored = context_usage(json.dumps(saved))
        self.assertEqual(restored['usedTokens'], 1234)
        self.assertEqual(restored['limitTokens'], 131072)
        self.assertEqual(restored['measuredAt'], window['measuredAt'])
        self.assertNotIn('private', json.dumps(saved))

    async def test_owner_is_checked_before_reading_stats(self):
        conversations = SimpleNamespace(require_owner=AsyncMock(side_effect=HTTPException(404)))
        runs = SimpleNamespace(latest_context_view=AsyncMock(return_value={'total_tokens': 5}))
        with self.assertRaises(HTTPException):
            await conversation_context_usage(10, 7, conversations, runs)
        runs.latest_context_view.assert_not_awaited()
        conversations.require_owner.side_effect = None
        result = await conversation_context_usage(10, 7, conversations, runs)
        self.assertEqual(result['usedTokens'], 5)
        runs.latest_context_view.assert_awaited_once_with(10, 7)

    async def test_new_chat_needs_no_database_or_checkpoint_read(self):
        result = await conversation_context_usage(None, 7, None, None)
        self.assertIsNone(result['usedTokens'])

    async def test_repository_selects_only_latest_numeric_view_for_owner(self):
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping={'context_view': '{"total_tokens":42}'})))
        result = await RunRepository(database).latest_context_view(10, 7)
        sql, args = database.fetch_one.call_args.args
        self.assertEqual(args, {'cid': 10, 'uid': 7})
        self.assertIn('context_views[last]', sql)
        self.assertNotIn('SELECT *', sql)
        self.assertEqual(context_usage(result)['usedTokens'], 42)
