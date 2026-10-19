"""Reconnect identity, producer leases, approval isolation and stale-executor fencing."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app import main
from app.config import settings
from app.services.executor_heartbeat import maintain_executor
from app.services.run_repository import RunRepository
from app.security.principal import Principal
from fakes import RUN_ID


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    def config(self, replay=False):
        return {'configurable': {'run_id': RUN_ID, 'execution_token': 'token', 'replay': replay}}

    async def test_live_producer_renews_while_no_http_reader_is_present(self):
        observed = asyncio.Event()
        async def renew(*args): observed.set()
        repo = SimpleNamespace(renew_executor=AsyncMock(side_effect=renew))
        with patch.object(settings, 'EXECUTOR_HEARTBEAT_SECONDS', .01):
            async with maintain_executor(repo, self.config()):
                await asyncio.wait_for(observed.wait(), 1)
        repo.renew_executor.assert_awaited_with(RUN_ID, 'token')
        calls = repo.renew_executor.await_count
        await asyncio.sleep(.03)
        self.assertEqual(repo.renew_executor.await_count, calls)

    async def test_lost_lease_stops_execution_instead_of_reviving_it(self):
        repo = SimpleNamespace(renew_executor=AsyncMock(side_effect=HTTPException(409, 'expired')))
        async def owner():
            async with maintain_executor(repo, self.config()):
                await asyncio.Event().wait()
        with patch.object(settings, 'EXECUTOR_HEARTBEAT_SECONDS', .01):
            task = asyncio.create_task(owner())
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        repo.renew_executor.assert_awaited_once()

    async def test_replay_does_not_renew_a_dead_executor(self):
        repo = SimpleNamespace(renew_executor=AsyncMock())
        with patch.object(settings, 'EXECUTOR_HEARTBEAT_SECONDS', .01):
            async with maintain_executor(repo, self.config(replay=True)):
                await asyncio.sleep(.03)
        repo.renew_executor.assert_not_awaited()

    async def test_settled_run_can_finish_delivery_without_being_cancelled(self):
        for status in ('succeeded', 'awaiting_approval'):
            observed = asyncio.Event()
            async def settled_run(*args):
                observed.set()
                return {'execution_token': 'token', 'status': status}
            repo = SimpleNamespace(renew_executor=AsyncMock(side_effect=HTTPException(409, 'settled')),
                get=AsyncMock(side_effect=settled_run))
            with patch.object(settings, 'EXECUTOR_HEARTBEAT_SECONDS', .01):
                async with maintain_executor(repo, self.config()):
                    await asyncio.wait_for(observed.wait(), 1)
            repo.get.assert_awaited_once()

    async def test_renew_is_fenced_by_token_status_lease_and_original_deadline(self):
        db = SimpleNamespace(execute=AsyncMock(), fetch_one=AsyncMock(return_value=None))
        with self.assertRaises(HTTPException):
            await RunRepository(db).renew_executor(RUN_ID, 'stale')
        sql, params = db.execute.call_args.args
        self.assertIn('LEAST(deadline', sql)
        self.assertIn('execution_token=:token', sql)
        self.assertIn("status='running'", sql)
        self.assertIn('executor_lease_until>UTC_TIMESTAMP(6)', sql)
        self.assertEqual(params['token'], 'stale')

    async def test_admission_cleanup_cannot_free_a_running_new_generation(self):
        db = SimpleNamespace(execute=AsyncMock())
        await RunRepository(db).release_admission(RUN_ID)
        sql = db.execute.call_args.args[0]
        self.assertIn('l.ticket=r.execution_token', sql)
        self.assertNotIn("'running'", sql)

    async def test_delivery_failure_diagnostics_cannot_overwrite_other_generation_or_committed_draft(self):
        import json
        db = SimpleNamespace(execute=AsyncMock())
        audit = {'status': 'unverified', 'remaining_findings': [{'block_index': 3, 'verdict': 'unsupported'}]}
        await RunRepository(db).record_delivery_failure(RUN_ID, 'current', audit, '未进入审批或保存')
        sql, params = db.execute.await_args.args
        for fence in ('execution_token=:token', "status='running'", 'draft_article_id IS NULL', "'$.draft_commit') IS NULL"):
            self.assertIn(fence, sql)
        self.assertEqual(params['token'], 'current')
        self.assertEqual(json.loads(params['audit']), audit)


class ConversationRunTests(unittest.IsolatedAsyncioTestCase):
    def fixture_run(self, status='running'):
        return {'run_id': RUN_ID, 'conversation_id': 11, 'user_id': 7, 'status': status,
            'execution_token': 'private-token', 'draft_hash': None, 'result_json': None,
            'deadline': datetime.utcnow() + timedelta(minutes=5), 'draft_article_id': None}

    async def test_owned_conversation_discovers_run_without_browser_run_id(self):
        run = self.fixture_run()
        repo = SimpleNamespace(latest=AsyncMock(return_value=run), expire_existing=AsyncMock(), get=AsyncMock(return_value=run))
        conv = SimpleNamespace(require_owner=AsyncMock())
        service = SimpleNamespace(reconcile_saved=AsyncMock(return_value=run))
        with patch.object(main, 'run_repository', repo), patch.object(main, 'conversation_service', conv), patch.object(main, 'run_service', service):
            result = await main.conversation_run(11, Principal(user_id=7))
        conv.require_owner.assert_awaited_once_with(11, 7)
        repo.latest.assert_awaited_once_with(11, 7)
        self.assertEqual(result['runId'], RUN_ID)
        self.assertEqual(result['conversationId'], '11')
        self.assertNotIn('execution_token', result)

    async def test_unowned_conversation_cannot_discover_an_executor(self):
        repo = SimpleNamespace(latest=AsyncMock())
        conv = SimpleNamespace(require_owner=AsyncMock(side_effect=HTTPException(404, 'not owned')))
        with patch.object(main, 'run_repository', repo), patch.object(main, 'conversation_service', conv), self.assertRaises(HTTPException):
            await main.conversation_run(11, Principal(user_id=8))
        repo.latest.assert_not_awaited()

    async def test_latest_status_is_reread_after_expiration(self):
        run = self.fixture_run()
        repo = SimpleNamespace(expire_existing=AsyncMock(), get=AsyncMock(return_value={**run, 'status': 'expired'}))
        service = SimpleNamespace(reconcile_saved=AsyncMock(return_value=run))
        with patch.object(main, 'run_repository', repo), patch.object(main, 'run_service', service):
            result = await main.reconciled_run_status(run, 7)
        self.assertEqual(result['status'], 'expired')

    async def test_model_timeout_emits_retryable_error_and_terminates_run(self):
        async def events(*args, **kwargs):
            raise TimeoutError('provider stalled')
            yield  # async generator contract
        repo = SimpleNamespace(fail=AsyncMock(), get=AsyncMock(return_value=None))
        service = SimpleNamespace(repository=repo, finish=AsyncMock())
        config = {'configurable': {'run_id': RUN_ID, 'execution_token': 'token'}}
        with patch.object(main, 'run_service', service):
            frames = [frame async for frame in main._stream_source(SimpleNamespace(astream_events=events), {}, 11, 7, config)]
        self.assertTrue(any('本次处理超时，已结束运行' in frame for frame in frames))
        self.assertEqual(frames[-1], 'data:[DONE]\n\n')
        repo.fail.assert_awaited_with(RUN_ID, 'token')
        service.finish.assert_not_awaited()

    async def test_draft_rejection_is_not_reported_as_service_outage(self):
        from app.services.grounding import DraftVerificationError
        from app.rpc.server import fault
        error = DraftVerificationError({'status': 'unverified', 'reason_code': 'content_rejected'})
        async def events(*args, **kwargs):
            raise error
            yield
        repo = SimpleNamespace(fail=AsyncMock(), get=AsyncMock(return_value=None))
        service = SimpleNamespace(repository=repo, finish=AsyncMock())
        config = {'configurable': {'run_id': RUN_ID, 'execution_token': 'token'}}
        with patch.object(main, 'run_service', service):
            frames = [frame async for frame in main._stream_source(SimpleNamespace(astream_events=events), {}, 11, 7, config)]
        self.assertTrue(any('[ERROR] 草稿依据核验未通过' in frame for frame in frames))
        self.assertFalse(any('Agent 处理失败' in frame or '已移除' in frame for frame in frames))
        self.assertIn('未进入审批或保存', fault(error).message)
        self.assertEqual(frames[-1], 'data:[DONE]\n\n')
