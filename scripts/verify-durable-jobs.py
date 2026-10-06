"""Isolated durability checks on real MySQL; all test rows roll back."""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.services.durable_jobs import DurableJobs, BackgroundWorker, LeaseLost
from app.services.memory import MemoryService, MemoryExtractResult, MemoryItem
from app.services.conversation import ConversationService
from app.migrate import apply_jobs_migration


async def main():
    report = {'checks': [], 'fixture_rolled_back': False}
    await db.connect()
    conversations = ConversationService()
    uid = await db.fetch_val("SELECT user_id FROM user_info WHERE email='rag-eval-v1@sample.invalid'")
    assert uid, 'Missing dedicated evaluation author'
    jobs = DurableJobs(db)
    ids = []
    def check(name): report['checks'].append(name)
    async def due(jid):
        await db.execute("UPDATE agent_background_job SET available_at='2000-01-01',created_at='2000-01-01' WHERE job_id=:id", {'id': jid})
    try:
        await apply_jobs_migration(db)
        await apply_jobs_migration(db)
        check('schema_migration_replay')
        async with db.transaction(force_rollback=True):
            cid = await conversations.create_conversation(uid)
            ids.append(cid)
            jid = await jobs.enqueue('fixture:'+uuid.uuid4().hex, 'memory_extract', uid, cid, {'upto_message_id': 0})
            await due(jid)
            check('durable_enqueue')
            row = await db.fetch_one('SELECT * FROM agent_background_job WHERE job_id=:id', {'id': jid})
            await jobs.enqueue('dedup:'+str(cid), 'memory_index', uid, cid, {'ids': []})
            j2 = await jobs.enqueue('dedup:'+str(cid), 'memory_index', uid, cid, {'ids': []})
            assert await db.fetch_val('SELECT COUNT(*) FROM agent_background_job WHERE job_id=:id', {'id': j2}) == 1
            check('idempotent_enqueue')
            first = await jobs.claim(); assert first['job_id'] == jid
            await db.execute("UPDATE agent_background_job SET lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE job_id=:id", {'id': jid})
            second = await jobs.claim(); assert second['job_id'] == jid and first['lease_token'] != second['lease_token']
            try:
                await jobs.assert_lease(first)
                raise AssertionError('stale executor passed lease fence')
            except LeaseLost:
                pass
            await jobs.complete(first)
            assert await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id', {'id': jid}) == 'running'
            check('expired_lease_reclaimed_and_old_executor_fenced')
            await jobs.retry(second, ConnectionError())
            row = dict((await db.fetch_one('SELECT status,last_error,available_at>UTC_TIMESTAMP(6) AS ready_later FROM agent_background_job WHERE job_id=:id', {'id': jid}))._mapping)
            assert row == {'status': 'pending', 'last_error': 'ConnectionError', 'ready_later': 1}
            check('failure_backoff')
            await due(jid)
            await db.execute('UPDATE agent_background_job SET attempts=7 WHERE job_id=:id', {'id': jid})
            last = await jobs.claim(); assert last['attempts'] == 8
            await jobs.retry(last, ConnectionError())
            assert await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id', {'id': jid}) == 'dead'
            check('eight_attempts_then_dead')
            await db.execute("UPDATE agent_background_job SET status='completed' WHERE job_id=:id", {'id': j2})

            extraction_id = await jobs.enqueue_extraction(uid, cid, 123)
            await due(extraction_id)
            extraction = await jobs.claim(); assert extraction['job_id'] == extraction_id
            control = SimpleNamespace(ainvoke=AsyncMock(return_value=MemoryExtractResult(memories=[MemoryItem(content='用户验证了可靠任务恢复。')])))
            service = MemoryService.__new__(MemoryService)
            service._llm = SimpleNamespace(with_structured_output=lambda *a, **kw: control)
            messages = [{'role': r, 'content': '验证恢复'} for r in ('user', 'assistant')]*2
            with patch.object(jobs, 'enqueue', AsyncMock(side_effect=ConnectionError('simulated DB write failure'))):
                try:
                    await service.extract_and_store(uid, cid, messages, job=extraction, jobs=jobs)
                    raise AssertionError('failed outbox insert did not roll back')
                except ConnectionError:
                    pass
            assert await db.fetch_val('SELECT COUNT(*) FROM user_memory WHERE source_conversation_id=:cid', {'cid': cid}) == 0
            assert await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id', {'id': extraction_id}) == 'running'
            check('memory_and_index_intent_rollback_together')
            await service.extract_and_store(uid, cid, messages, job=extraction, jobs=jobs)
            assert await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id', {'id': extraction_id}) == 'completed'
            memories = await db.fetch_all('SELECT memory_id FROM user_memory WHERE source_conversation_id=:cid', {'cid': cid})
            assert len(memories) == 1
            mid = memories[0]._mapping['memory_id']
            index_id = await db.fetch_val("SELECT job_id FROM agent_background_job WHERE conversation_id=:cid AND kind='memory_index' AND status='pending'", {'cid': cid})
            await due(index_id)
            index_job = await jobs.claim(); assert index_job['kind'] == 'memory_index' and mid in index_job['payload']['ids']
            check('memory_commit_index_intent_and_completion_atomic')
            from app.services.memory import memory_service
            worker = BackgroundWorker(jobs)
            with patch.object(memory_service, 'sync_changes', AsyncMock(return_value=False)):
                try:
                    await worker.handle(index_job)
                    raise AssertionError('index outage swallowed')
                except ConnectionError:
                    pass
            await jobs.retry(index_job, ConnectionError())
            await due(index_job['job_id'])
            index_job = await jobs.claim()
            await db.execute("UPDATE user_memory SET status='inactive' WHERE memory_id=:mid", {'mid': mid})
            with patch.object(memory_service, 'sync_changes', AsyncMock(return_value=True)) as sync:
                await worker.handle(index_job)
                sync.assert_awaited_once_with([], [mid])
            check('failed_index_retries_and_inactive_memory_is_not_resurrected')
        report['fixture_rolled_back'] = not await db.fetch_val('SELECT COUNT(*) FROM ai_conversation WHERE conversation_id=:cid', {'cid': ids[0]})
        assert report['fixture_rolled_back']
    finally:
        await conversations._redis.client.aclose()
        await db.disconnect()
    (ROOT / 'logs/optimization-durability-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

asyncio.run(main())
