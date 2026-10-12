import os
os.environ.setdefault('DEEPSEEK_API_KEY', 'offline-test')
os.environ.setdefault('AGENT_SERVICE_KEY', 'offline-service-key-32-bytes-long!!')
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import HTTPException
from app.services.history_pages import HistoryPages
from app.services.run_history import RunHistory


def row(**values):
    return SimpleNamespace(_mapping=values)


class HistoryPagesTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[]), fetch_val=AsyncMock(return_value=100))
        runs = SimpleNamespace(history=AsyncMock(side_effect=lambda cid, uid, items, **kw: items))
        repo = SimpleNamespace(pending_approval=AsyncMock(return_value=None))
        return HistoryPages(database, runs, repo)

    async def test_older_window_is_bounded_by_complete_user_turns(self):
        service = self.service()
        service.users = AsyncMock(side_effect=[[11, 21], [31], [1]])
        service.db.fetch_all.return_value = [row(message_id=n, role=role, content='x')
            for n, role in [(11, 'user'), (12, 'assistant'), (13, 'assistant'), (21, 'user'), (22, 'assistant')]]
        page = await service.page(9, 7, 2, before=31)
        sql, params = service.db.fetch_all.await_args.args
        self.assertIn('message_id < :end', sql)
        self.assertEqual(params, {'cid': 9, 'start': 11, 'end': 31, 'ceiling': 100})
        self.assertIn('message_id<=:ceiling', sql)
        self.assertEqual([m['turnId'] for m in page['items']], ['11', '11', '11', '21', '21'])
        self.assertTrue(page['hasOlder'] and page['hasNewer'])
        service.runs.history.assert_awaited_once_with(9, 7, unittest.mock.ANY, turn_ids=[11, 21])
        service.repository.pending_approval.assert_not_awaited()

    async def test_around_unknown_or_other_conversation_message_is_denied(self):
        service = self.service()
        service.db.fetch_val.return_value = None
        with self.assertRaises(HTTPException) as error:
            await service.page(9, 7, around=55)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(service.db.fetch_val.await_args.args[1], {'cid': 9, 'mid': 55})

    async def test_cursor_directions_are_mutually_exclusive(self):
        service = self.service()
        with self.assertRaises(HTTPException) as error:
            await service.page(9, 7, before=5, after=10)
        self.assertEqual(error.exception.status_code, 422)
        service.db.fetch_all.assert_not_awaited()

    async def test_latest_pending_approval_has_stable_run_identity(self):
        service = self.service()
        service.repository.pending_approval.return_value = {'runId': 'r1', 'draft': 'preview'}
        page = await service.finish(9, 7, [{'messageId': '5', 'role': 'user'}], [5], True, False)
        self.assertEqual(page['items'][1]['itemId'], 'run:r1')
        self.assertEqual(page['items'][1]['turnId'], '5')
        self.assertTrue(page['items'][1]['interrupted'])

    async def test_question_index_uses_snapshot_and_short_previews(self):
        service = self.service()
        service.db.fetch_all.return_value = [row(messageId=str(n), question='q', answer='a', hasImage=0) for n in [5, 7, 9]]
        page = await service.questions(9, after=3, limit=2, snapshot=9)
        self.assertTrue(page['hasMore'])
        self.assertEqual(page['nextCursor'], '7')
        service.db.fetch_val.assert_not_awaited()
        sql, params = service.db.fetch_all.await_args.args
        self.assertIn('LEFT(m.content,256)', sql)
        self.assertIn('LEFT(a.content,384)', sql)
        self.assertEqual(params, {'cid': 9, 'snapshot': 9, 'after': 3, 'lim': 3})
        # LEAD must include newly appended questions to keep the final snapshot turn's boundary correct.
        self.assertNotIn('message_id<=:snapshot)', sql)

    async def test_failure_events_are_fetched_only_for_selected_turns(self):
        database = SimpleNamespace(fetch_all=AsyncMock(side_effect=[[
            row(run_id='r1', status='failed', draft_article_id=None, created_at=datetime(2026,10,11), updated_at=datetime(2026,10,11),
                result_json='{"user_message_id":"5"}')], [], []]))
        service = RunHistory(database)
        await service.history(9, 7, [{'messageId': '5', 'role': 'user'}], turn_ids=[5])
        calls = database.fetch_all.await_args_list
        self.assertIn('IN (:t0)', calls[0].args[0])
        self.assertEqual(calls[0].args[1]['t0'], '5')
        for call in calls[1:]:
            self.assertIn('e.run_id IN (:r0)', call.args[0])
            self.assertEqual(call.args[1]['r0'], 'r1')
