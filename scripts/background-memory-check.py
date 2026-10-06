"""Disposable local MySQL/HTTP checks; Main and embedding providers are not called."""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.models.memory_change import MemoryChange
from app.graph.state_factory import create_initial_state
from app.services.memory_policy import MemoryPolicyService
from app.services.durable_jobs import BackgroundWorker, DurableJobs
from app.services.run_repository import RunRepository
from app.services.conversation import ConversationService
from app.services.memory import memory_service
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    assert db.url.hostname in ('127.0.0.1', 'localhost', '::1')
    uid = SnowflakeGenerator(worker_id=25).next_id()
    marker = 'background-memory-' + uuid4().hex[:8]
    cids, rids, checks = [], [], []
    passed = False
    await db.connect()
    service = MemoryPolicyService(db)
    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        print(name + ': ' + str(bool(value)), flush=True)
        assert value, name
    async def prepare(message):
        cid = await ConversationService().create_conversation(uid)
        cids.append(cid)
        await db.execute('UPDATE ai_conversation SET title=:title WHERE conversation_id=:cid AND user_id=:uid',
                         {'title': marker, 'cid': cid, 'uid': uid})
        run, _ = await RunRepository(db).create(cid, uid, str(uuid4()), uuid4().hex)
        rids.append(run['run_id'])
        s = create_initial_state(uid, message, [])
        s.update(conversation_id=cid, run_id=run['run_id'], execution_token=run['execution_token'],
                 **await service.load_context(uid, cid))
        return s
    async def delayed(s, changes):
        async with db.transaction():
            update = await service.enqueue_changes(s, changes)
            await db.execute('UPDATE agent_background_job SET available_at=TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP(6)) WHERE job_id=:id',
                             {'id': update['memory_write_job_id']})
        return update['memory_write_job_id']
    async def release(jid, s, status='succeeded'):
        async with db.transaction():
            await db.execute('UPDATE agent_run SET status=:status WHERE run_id=:rid AND user_id=:uid',
                             {'rid': s['run_id'], 'uid': uid, 'status': status})
            await db.execute('UPDATE agent_background_job SET available_at=UTC_TIMESTAMP(6) WHERE job_id=:id AND user_id=:uid',
                             {'id': jid, 'uid': uid})
        for _ in range(60):
            row = await db.fetch_one('SELECT status,payload FROM agent_background_job WHERE job_id=:id AND user_id=:uid', {'id': jid, 'uid': uid})
            if row._mapping['status'] == 'completed': return json.loads(row._mapping['payload'])['outcome']
            if row._mapping['status'] == 'dead': raise AssertionError('job failed')
            await asyncio.sleep(.25)
        raise TimeoutError('local background worker did not complete')
    async def profile():
        return (await service.load_context(uid, cids[-1]))['user_profile']
    try:
        await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,
            total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,:name,:email,'LocalMemoryQa2026!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''',
            {'uid': uid, 'name': '记忆验证' + str(uid)[-10:], 'email': marker + '@sample.invalid', 'marker': marker})
        s = await prepare('以后默认简短回答，帮我解释Redis')
        c = MemoryChange(kind='profile', scope='user', key='preferences.detail', value='brief', source_quote='以后默认简短回答')
        jid = await delayed(s, [c])
        check('accepted_write_does_not_mutate_profile', not (await profile()).get('preferences'))
        replay = await service.enqueue_changes(s, [c])
        check('same_run_replay_keeps_one_job', replay['memory_write_job_id'] == jid)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', trust_env=False,
            headers={'Authorization': 'Bearer ' + local_token(uid)}, timeout=15) as client:
            async def overview():
                response = await client.get('/agent/memory')
                assert response.status_code == 200 and response.json()['code'] == 200
                return response.json()['data']
            check('http_reports_pending_without_private_payload',
                  (await overview())['write_jobs'][0]['status'] == 'pending'
                  and set((await overview())['write_jobs'][0]) == {'id', 'status', 'updated_at'})
            check('finished_run_saved_by_live_background_worker', await release(jid, s) == 'succeeded')
            check('profile_is_authoritative_after_background_commit', (await profile())['preferences']['detail'] == 'brief')
            check('http_reports_success', (await overview())['write_jobs'][0]['status'] == 'succeeded')
            s = await prepare('以后默认详细回答')
            c = c.model_copy(update={'value': 'detailed', 'source_quote': s['user_message']})
            jid = await delayed(s, [c])
            await db.execute('UPDATE user_profile SET preferences=:pref WHERE user_id=:uid', {'uid': uid, 'pref': '{"detail":"examples"}'})
            check('concurrent_edit_reports_conflict', await release(jid, s) == 'conflict')
            check('concurrent_edit_is_not_overwritten', (await profile())['preferences']['detail'] == 'examples')
            s = await prepare('以后默认简短回答')
            c = c.model_copy(update={'value': 'brief', 'source_quote': s['user_message']})
            jid = await delayed(s, [c])
            check('cancelled_run_drops_pending_write', await release(jid, s, 'cancelled') == 'cancelled')
            check('cancellation_preserves_profile', (await profile())['preferences']['detail'] == 'examples')
            s = await prepare('本会话不联网')
            c = MemoryChange(kind='constraint', key='web_search', value='deny', source_quote=s['user_message'])
            jid = await delayed(s, [c])
            check('constraint_saved_after_run_finish', await release(jid, s) == 'succeeded')
            context = await service.load_context(uid, s['conversation_id'])
            check('saved_constraint_has_backend_record_id', len(context['active_constraints']) == 1
                  and context['active_constraints'][0]['id'].isdigit())
            s = await prepare('把已确认的缓存方案改为Canal，以后以这个为准')
            old_id = SnowflakeGenerator(worker_id=25).next_id()
            await db.execute('''INSERT INTO user_memory(memory_id,user_id,content,importance,source_conversation_id,
                create_time,update_time,memory_type,scope,scope_conversation_id,status,memory_key)
                VALUES(:id,:uid,'Cache Aside',0.8,:cid,NOW(),NOW(),'decision','user',NULL,'active','cache_strategy')''',
                {'id': old_id, 'uid': uid, 'cid': s['conversation_id']})
            s['task_results'] = {'lookup': {'status': 'succeeded', 'retrieval_target': 'memory',
                'memory_sources': [{'id': f'memory:{old_id}', 'type': 'decision', 'scope': 'user', 'key': 'cache_strategy'}]}}
            c = MemoryChange(kind='decision', scope='user', key='cache_strategy', value='Canal',
                             record_id=str(old_id), source_quote=s['user_message'])
            jid = await delayed(s, [c])
            token = str(uuid4())
            async with db.transaction():
                await db.execute('UPDATE agent_run SET status=\'succeeded\' WHERE run_id=:rid AND user_id=:uid', {'rid': s['run_id'], 'uid': uid})
                await db.execute('''UPDATE agent_background_job SET status='running',attempts=1,lease_token=:token,
                    lease_until=TIMESTAMPADD(SECOND,120,UTC_TIMESTAMP(6)) WHERE job_id=:id AND user_id=:uid''', {'id': jid, 'uid': uid, 'token': token})
                row = await db.fetch_one('SELECT * FROM agent_background_job WHERE job_id=:id', {'id': jid})
                job = dict(row._mapping); job['payload'] = json.loads(job['payload'])
                await service.process_write(job)
                # Keep the disposable decision's index stage local; no paid embedding provider.
                await db.execute("UPDATE agent_background_job SET available_at=TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP(6)) WHERE user_id=:uid AND kind='memory_index' AND status='pending'", {'uid': uid})
            records = await db.fetch_all("SELECT memory_id,content,status FROM user_memory WHERE user_id=:uid AND memory_type='decision'", {'uid': uid})
            check('decision_replacement_is_atomic_and_preserves_old_history', len(records) == 2 and
                  sorted((r._mapping['content'], r._mapping['status']) for r in records) == [('Cache Aside', 'inactive'), ('Canal', 'active')])
            index_row = await db.fetch_one("SELECT * FROM agent_background_job WHERE user_id=:uid AND kind='memory_index' AND status='pending' ORDER BY created_at DESC LIMIT 1", {'uid': uid})
            index_job = dict(index_row._mapping); index_job['payload'] = json.loads(index_job['payload'])
            await db.execute("UPDATE agent_background_job SET status='running',lease_token=:token,lease_until=TIMESTAMPADD(SECOND,120,UTC_TIMESTAMP(6)) WHERE job_id=:id", {'id': index_job['job_id'], 'token': token})
            index_job['lease_token'] = token
            with patch.object(memory_service, 'sync_changes', AsyncMock(return_value=True)) as sync:
                await BackgroundWorker(DurableJobs(db)).handle(index_job)
                upserts, deletes = sync.await_args.args
                check('index_stage_uses_authoritative_new_record_and_deletes_old_id', len(upserts) == 1
                      and upserts[0]['content'] == 'Canal' and old_id in deletes)
            check('http_lists_saved_decision_without_old_active_record',
                  any(m['content'] == 'Canal' and m['status'] == 'active' for m in (await overview())['memories']))
        if '--preview' in sys.argv:
            print('Preview login: ' + marker + '@sample.invalid / LocalMemoryQa2026!', flush=True)
            print('Press Enter after browser verification to clean fixtures.', flush=True)
            await asyncio.to_thread(input)
        passed = True
    finally:
        owner = await db.fetch_one('SELECT person_introduction FROM user_info WHERE user_id=:uid', {'uid': uid})
        if owner:
            assert owner._mapping['person_introduction'] == marker
            async with db.transaction():
                await db.execute('DELETE FROM agent_background_job WHERE user_id=:uid', {'uid': uid})
                for table in ('user_memory_change', 'user_memory', 'user_profile', 'agent_run', 'ai_conversation'):
                    await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker', {'uid': uid, 'marker': marker})
        await db.disconnect()
        output = ROOT / 'logs' / 'evaluation' / ('background-memory-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
        output.write_text(json.dumps({'passed': passed, 'checks': checks, 'cleanup_complete': True,
            'scope': 'real local MySQL + live background worker + Java HTTP; model calls omitted; decision ES adapter mocked'}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Report: ' + str(output), flush=True)
    return 0 if passed else 1

if __name__ == '__main__': raise SystemExit(asyncio.run(main()))
