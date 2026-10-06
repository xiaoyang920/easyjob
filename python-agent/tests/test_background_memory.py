"""Queue acceptance, cancellation, leases, concurrent edits and current-turn policy."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.models.memory_change import MemoryChange, validate_memory_changes
from app.models.memory_overlay import turn_memory_context
from app.services.memory_policy import MemoryPolicyService
from app.services.durable_jobs import BackgroundWorker, DurableJobs, LeaseLost
from app.graph.staged_runtime import task_context
from app.graph.staged_plan import ExecutionTask
from app.security.capabilities import effective_capabilities
from app.config import settings
from app.graph import main_agent as agent
from app.graph.main_agent import MainDecision, RetrievalRequest, memory_pending_reply
from test_main_agent import llm
from test_structured_memory import MemoryDatabase, state, change, row


class QueueDatabase(MemoryDatabase):
    def __init__(self):
        super().__init__()
        self.run_status = 'running'
        self.conversation_status = 1
    async def fetch_one(self, sql, params):
        if 'FROM ai_conversation' in sql:
            return row(status=self.conversation_status)
        if 'SELECT status FROM agent_run' in sql:
            return row(status=self.run_status)
        if 'FROM agent_background_job' in sql:
            job = self.jobs.get(params['id'])
            if not job: return None
            if 'lease_token=:token' in sql and (job['status'] != 'running' or job['lease_token'] != params['token']): return None
            return row(**job)
        return await super().fetch_one(sql, params)
    async def execute(self, sql, params):
        if 'INSERT IGNORE INTO agent_background_job' in sql:
            self.jobs.setdefault(params['id'], {**copy.deepcopy(params), 'job_id': params['id'],
                'status': 'pending', 'lease_token': 'lease', 'attempts': 1})
            return
        if 'UPDATE agent_background_job SET' in sql:
            job = self.jobs[params['id']]
            payload = json.loads(job['payload'])
            payload['outcome'] = params['outcome']
            job.update(payload=json.dumps(payload), status='completed')
            return
        return await super().execute(sql, params)
    def claimed(self, jid):
        self.jobs[jid]['status'] = 'running'
        return {**self.jobs[jid], 'user_id': 7, 'conversation_id': 11, 'payload': json.loads(self.jobs[jid]['payload'])}


class BackgroundMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = QueueDatabase()
        self.service = MemoryPolicyService(self.db)

    async def submit(self, s=None, changes=None):
        s = s or state()
        update = await self.service.enqueue_changes(s, changes or [change()])
        return self.db.claimed(update['memory_write_job_id'])

    async def test_acceptance_never_mutates_profile_or_calls_index_and_replay_is_idempotent(self):
        with patch('app.services.memory.memory_service.sync_changes', AsyncMock()) as index:
            first = await self.service.enqueue_changes(state(), [change()])
            second = await self.service.enqueue_changes(state(), [change()])
        self.assertEqual(first['memory_write_job_id'], second['memory_write_job_id'])
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(self.db.profile['preferences'], '{}')
        self.assertEqual(self.db.receipts, {})
        index.assert_not_awaited()
        with self.assertRaises(ValueError):
            await self.service.enqueue_changes(state(), [change().model_copy(update={'value': 'detailed'})])

    async def test_finished_run_can_save_and_db_commit_creates_index_job_atomically(self):
        job = await self.submit()
        self.db.run_status = 'succeeded'
        with patch('app.services.memory.memory_service.sync_changes', AsyncMock()) as index:
            await BackgroundWorker(DurableJobs(self.db)).handle(job)
        self.assertEqual(json.loads(self.db.profile['preferences']), {'detail': 'brief'})
        self.assertEqual(json.loads(self.db.jobs[job['job_id']]['payload'])['outcome'], 'succeeded')
        self.assertTrue(any(j['kind'] == 'memory_index' for j in self.db.jobs.values()))
        index.assert_not_awaited()

    async def test_concurrent_edit_keeps_new_value_and_reports_conflict_without_retry(self):
        job = await self.submit()
        self.db.profile['preferences'] = '{"detail":"detailed"}'
        await self.service.process_write(job)
        self.assertEqual(json.loads(self.db.profile['preferences']), {'detail': 'detailed'})
        self.assertEqual(json.loads(self.db.jobs[job['job_id']]['payload'])['outcome'], 'conflict')
        self.assertFalse(self.db.receipts)

    async def test_cancelled_run_or_deleted_conversation_never_writes_memory(self):
        for cancelled in (True, False):
            self.db = QueueDatabase(); self.service = MemoryPolicyService(self.db)
            job = await self.submit()
            if cancelled: self.db.run_status = 'cancelled'
            else: self.db.conversation_status = 0
            await self.service.process_write(job)
            self.assertEqual(self.db.profile['preferences'], '{}')
            self.assertEqual(json.loads(self.db.jobs[job['job_id']]['payload'])['outcome'], 'cancelled')

    async def test_stale_lease_cannot_commit_or_acknowledge(self):
        job = await self.submit()
        self.db.jobs[job['job_id']]['lease_token'] = 'new-executor'
        with self.assertRaises(LeaseLost): await self.service.process_write(job)
        self.assertEqual(self.db.profile['preferences'], '{}')
        self.assertEqual(self.db.jobs[job['job_id']]['status'], 'running')

    async def test_receipt_failure_rolls_back_memory_and_is_retryable(self):
        job = await self.submit(); self.db.fail_receipt = True
        with self.assertRaises(RuntimeError): await self.service.process_write(job)
        self.assertEqual(self.db.profile['preferences'], '{}')
        self.assertEqual(self.db.jobs[job['job_id']]['status'], 'running')
        self.assertEqual(len(self.db.jobs), 1)
        self.db.fail_receipt = False
        await self.service.process_write(job)
        self.assertEqual(json.loads(self.db.profile['preferences']), {'detail': 'brief'})

    async def test_queue_acceptance_rejects_cancelled_executor(self):
        self.db.alive = False
        with self.assertRaises(HTTPException): await self.submit()
        self.assertFalse(self.db.jobs)

    async def test_main_never_continues_after_authorization_or_cancellation_failure(self):
        decision = MainDecision(action='retrieve', retrieval=RetrievalRequest(instruction='find'), memory_changes=[change()])
        model, _ = llm([decision])
        with patch.object(agent, 'get_llm', return_value=model), \
             patch.object(agent, 'assert_run', AsyncMock()), \
             patch.object(agent.memory_policy_service, 'enqueue_changes', AsyncMock(side_effect=HTTPException(409, 'cancelled'))), \
             patch.object(agent, 'publish_route', AsyncMock()) as route:
            with self.assertRaises(HTTPException): await agent.decide_main_action(state())
        route.assert_not_awaited()

    def test_model_cannot_claim_pending_memory_was_saved(self):
        for reply in ('好的，已记住了。', '偏好已经保存到长期记忆。', '我已删除你的记忆。'):
            result = memory_pending_reply(reply, 'pending')
            self.assertNotIn('已记住', result)
            self.assertNotIn('已经保存', result)
            self.assertNotIn('已删除', result)
            self.assertIn('后台保存', result)

    def test_turn_projection_is_separate_and_pending_web_rule_is_enforced(self):
        s = state('本会话不要联网，以后默认简短回答')
        changes = [change(), MemoryChange(kind='constraint', key='web_search', value='deny', source_quote='本会话不要联网')]
        s.update(pending_memory_changes=[c.model_dump() for c in changes], memory_changes_queued=True)
        self.assertEqual(turn_memory_context(s)['user_profile']['preferences']['detail'], 'brief')
        self.assertEqual(s['user_profile'], {})
        task = ExecutionTask(task_id='find', kind='search', actor='main', instruction='find', allow_web=True)
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            self.assertNotIn('web_search', effective_capabilities(task_context(s, task)))
        with self.assertRaises(ValueError): validate_memory_changes(s, [change()])

    def test_turn_replacement_and_removal_do_not_change_the_saved_snapshot(self):
        s = state('取消本会话禁止联网')
        s['active_constraints'] = [{'id': '42', 'key': 'web_search', 'scope': 'conversation', 'content': 'deny'}]
        c = MemoryChange(kind='constraint', key='web_search', operation='remove', record_id='42', source_quote=s['user_message'])
        s['pending_memory_changes'] = [c.model_dump()]
        self.assertEqual(turn_memory_context(s)['active_constraints'], [])
        self.assertEqual(s['active_constraints'][0]['content'], 'deny')
