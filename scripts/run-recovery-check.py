"""Local real SQL/HTTP run recovery checks; owned fixtures, no model calls."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.services.run_repository import RunRepository, digest
from app.services.conversation import ConversationService
from app.services.stream_delivery import StreamDelivery
from app.services.execution_admission import ExecutionAdmission
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import HTTPException


async def main():
    if db.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('Local recovery fixtures only')
    uid = SnowflakeGenerator(worker_id=25).next_id()
    marker = 'recovery-' + uuid4().hex[:8]
    cid, delivery = None, None
    report = {'checks': [], 'cleanup_complete': False, 'scope': 'real local MySQL, Java HTTP and detached stream producer; no model calls'}
    output = ROOT / 'logs/evaluation' / f'run-recovery-{datetime.now():%Y%m%d-%H%M%S}.json'
    def check(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        print(name + ': ' + str(bool(condition)), flush=True)
        if not condition: raise AssertionError(name)
    await db.connect()
    try:
        await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
            sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES(:uid,:name,:email,'NotALoginCredential!',:name,NOW(),2,1,0,0,1,1,0,0,0)''',
            {'uid': uid, 'name': marker, 'email': marker + '@sample.invalid'})
        cid = await ConversationService().create_conversation(uid)
        repo = RunRepository(db)
        ticket = await ExecutionAdmission(db).acquire(uid)
        run, _ = await repo.create(cid, uid, str(uuid4()), digest({'fixture': marker}))
        rid, token = run['run_id'], run['execution_token']
        await repo.bind_admission(rid, token, ticket)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', trust_env=False,
                headers={'Authorization': 'Bearer ' + local_token(uid)}, timeout=15) as client:
            async def status():
                response = await client.get(f'/agent/conversations/{cid}/run')
                response.raise_for_status()
                body = response.json()
                check('java_status_contract_' + str(len(report['checks'])), body['code'] == 200)
                return body['data']
            initial = await status()
            check('new_tab_discovers_running_run_without_run_id', initial['runId'] == rid and initial['status'] == 'running')
            check('executor_token_not_exposed', 'execution_token' not in initial and 'executionToken' not in initial)
            ready, release = asyncio.Event(), asyncio.Event()
            payload = {'runId': rid, 'draftHash': 'a' * 64, 'draft': 'isolated preview'}
            result = {'reply': '', 'interrupted': payload, 'draft_article_id': None, 'articles': [], 'citations': []}
            async def source():
                yield 'data:__RUN_ID__:' + rid + '\n\n'
                ready.set()
                await release.wait()
                await repo.settle(cid, uid, rid, token, 'awaiting_approval', result)
                yield 'data:[DONE]\n\n'
            delivery = StreamDelivery(db, ExecutionAdmission(db), repo)
            delivery.start(rid, token, source(), token)
            await asyncio.wait_for(ready.wait(), 5)
            reader = delivery.follow(rid, token)
            await anext(reader)
            await reader.aclose()
            check('closing_subscriber_does_not_cancel_execution', (rid, token) in delivery.tasks)
            before = (await repo.get(rid))['executor_lease_until']
            await asyncio.sleep(settings.EXECUTOR_HEARTBEAT_SECONDS + 1)
            after = (await repo.get(rid))['executor_lease_until']
            check('detached_producer_keeps_heartbeat_alive', after > before)
            check('another_page_can_find_detached_execution', (await status())['status'] == 'running')
            release.set()
            await asyncio.wait_for(asyncio.gather(*list(delivery.tasks.values())), 5)
            # A stale executor heartbeat must not expire the human approval deadline.
            await db.execute('UPDATE agent_run SET executor_lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid', {'rid': rid})
            pending = await status()
            check('pending_approval_survives_without_executor_heartbeat', pending['status'] == 'awaiting_approval' and pending['result']['interrupted']['draft'] == 'isolated preview')
            claimed = await repo.claim_resume(cid, uid, rid, 'a' * 64)
            resume_ticket = await ExecutionAdmission(db).acquire(uid)
            await repo.bind_admission(rid, claimed['execution_token'], resume_ticket)
            try: await repo.renew_executor(rid, token)
            except HTTPException as error: check('old_resume_generation_cannot_renew', error.status_code == 409)
            else: check('old_resume_generation_cannot_renew', False)
            await db.execute('UPDATE agent_run SET executor_lease_until=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE run_id=:rid', {'rid': rid})
            check('lost_executor_released_before_five_minute_deadline', (await status())['status'] == 'expired')
            leases = await db.fetch_val('SELECT COUNT(*) FROM agent_execution_lease WHERE user_id=:uid', {'uid': uid})
            check('lost_executor_also_releases_global_capacity', leases == 0)
            try: await repo.renew_executor(rid, claimed['execution_token'])
            except HTTPException as error: check('expired_executor_cannot_resurrect', error.status_code == 409)
            else: check('expired_executor_cannot_resurrect', False)
            new_run, created = await repo.create(cid, uid, str(uuid4()), digest({'fixture': marker, 'retry': True}))
            check('conversation_accepts_new_request_after_lease_loss', created and new_run['run_id'] != rid)
            try: await repo.settle(cid, uid, rid, claimed['execution_token'], 'succeeded', {'reply': 'stale'})
            except HTTPException as error: check('old_executor_cannot_deliver_after_new_run', error.status_code == 409)
            else: check('old_executor_cannot_deliver_after_new_run', False)
            count = await db.fetch_val('SELECT COUNT(*) FROM agent_run WHERE active_conversation_id=:cid', {'cid': cid})
            check('one_active_run_per_conversation', count == 1)
            response = await client.get(f'/agent/conversations/{cid}/run', headers={'Authorization': 'Bearer ' + local_token(uid + 1)})
            check('foreign_user_cannot_discover_run', response.status_code == 404 or response.json().get('code') == 404)
    finally:
        if delivery: await delivery.shutdown()
        if cid:
            owned = await db.fetch_val('SELECT user_id FROM ai_conversation WHERE conversation_id=:cid', {'cid': cid})
            if owned != uid: raise RuntimeError('Fixture ownership changed; cleanup stopped')
            await db.execute('DELETE f FROM agent_stream_frame f JOIN agent_run r ON f.run_id=r.run_id WHERE r.conversation_id=:cid AND r.user_id=:uid', {'cid': cid, 'uid': uid})
            await db.execute('DELETE e FROM agent_run_event e JOIN agent_run r ON e.run_id=r.run_id WHERE r.conversation_id=:cid AND r.user_id=:uid', {'cid': cid, 'uid': uid})
            await db.execute('DELETE FROM agent_run WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid', {'cid': cid, 'uid': uid})
        await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker', {'uid': uid, 'marker': marker})
        await db.execute('DELETE FROM agent_execution_lease WHERE user_id=:uid', {'uid': uid})
        report['cleanup_complete'] = True
        report['passed'] = bool(report['checks']) and all(c['passed'] for c in report['checks'])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        await db.disconnect()
        print('Report: ' + str(output))


if __name__ == '__main__': asyncio.run(main())
