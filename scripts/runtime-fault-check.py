"""Local MySQL/Redis integration checks with isolated fixtures, no paid LLM calls."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.services.execution_admission import ExecutionAdmission
from app.services.stream_delivery import StreamDelivery
from app.services.run_repository import RunRepository, digest
from app.services.durable_jobs import DurableJobs, LeaseLost
from app.services.operations import Operations
from app.utils.snowflake import SnowflakeGenerator
from fastapi import HTTPException


async def main():
    if db.url.hostname not in {'localhost','127.0.0.1','::1'}: raise RuntimeError('local fixtures only')
    ids=SnowflakeGenerator(worker_id=28); uid=ids.next_id(); cid=ids.next_id()
    marker=f'fault-{uuid4().hex}@sample.invalid'; report={'checks':[], 'cleanup_complete':False,'scope':'real local SQL/Redis; deterministic graph; no LLM calls'}
    output=ROOT/'logs/evaluation'/f'runtime-fault-{datetime.now():%Y%m%d-%H%M%S}.json'
    tickets=[]; tasks=[]; created=False; delivery=None
    def check(name, condition, **details):
        value={'name':name,'passed':bool(condition),**details}; report['checks'].append(value)
        print(json.dumps(value,ensure_ascii=False),flush=True)
        if not condition: raise AssertionError(name)
    await db.connect()
    try:
        if await db.fetch_val('SELECT COUNT(*) FROM agent_execution_lease WHERE expires_at>UTC_TIMESTAMP(6)'):
            raise RuntimeError('Agent is busy; retry the isolated admission checks later')
        await db.execute("""INSERT INTO user_info (user_id,nick_name,email,password,person_introduction,join_time,sex,status,
            total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
            VALUES (:uid,'故障验证',:marker,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)""",{'uid':uid,'marker':marker})
        created=True
        await db.execute("""INSERT INTO ai_conversation (conversation_id,user_id,message_count,total_tokens,status,create_time,update_time)
            VALUES (:cid,:uid,0,0,1,NOW(),NOW())""",{'cid':cid,'uid':uid})
        admission=ExecutionAdmission(db)
        with patch.object(settings,'EXECUTION_GLOBAL_LIMIT',2), patch.object(settings,'EXECUTION_USER_LIMIT',1), \
             patch.object(settings,'EXECUTION_QUEUE_LIMIT',2), patch.object(settings,'EXECUTION_WAIT_SECONDS',2):
            tickets.extend([await admission.acquire(uid), await admission.acquire(uid+1)])
            waiter1=asyncio.create_task(admission.acquire(uid+2)); waiter2=asyncio.create_task(admission.acquire(uid+3)); tasks.extend([waiter1,waiter2])
            for _ in range(40):
                if await db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='waiting'")==2: break
                await asyncio.sleep(.025)
            try: await admission.acquire(uid+4)
            except HTTPException as e: check('queue_full_returns_429',e.status_code==429)
            else: check('queue_full_returns_429',False)
            active=await db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='active'")
            check('global_active_limit',active==2,active=active)
            await admission.release(tickets.pop(0))
            done,_=await asyncio.wait([waiter1,waiter2],timeout=1,return_when=asyncio.FIRST_COMPLETED)
            check('queued_request_admitted_after_release',len(done)==1)
            for task in done: tickets.append(task.result())
            remaining=waiter2 if waiter1 in done else waiter1
            try: await remaining
            except HTTPException as e: check('queue_timeout_returns_429',e.status_code==429)
            else: check('queue_timeout_returns_429',False)
            for ticket in tickets: await admission.release(ticket)
            tickets.clear()
            a=await admission.acquire(uid); tickets.append(a)
            same=asyncio.create_task(admission.acquire(uid)); tasks.append(same)
            await asyncio.sleep(.35)
            check('per_user_limit_despite_free_global_slot',not same.done())
            same.cancel(); await asyncio.gather(same,return_exceptions=True)
            check('cancelled_waiter_is_removed',await db.fetch_val("SELECT COUNT(*) FROM agent_execution_lease WHERE state='waiting'")==0)
            await db.execute('UPDATE agent_execution_lease SET expires_at=TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)) WHERE ticket=:t',{'t':a})
            b=await admission.acquire(uid); tickets.append(b)
            check('expired_admission_lease_is_reclaimed',await db.fetch_val('SELECT COUNT(*) FROM agent_execution_lease WHERE ticket=:t',{'t':a})==0)
            for ticket in tickets: await admission.release(ticket)
            tickets.clear()

        # Drive the production producer/settlement code, while deliberately closing its HTTP reader.
        from app import main as api
        run,_=await RunRepository(db).create(cid,uid,str(uuid4()),digest('stream-fault'))
        ready,release=asyncio.Event(),asyncio.Event(); graph_calls=[]
        class Graph:
            async def astream_events(self,*args,**kwargs):
                graph_calls.append(True); ready.set(); await release.wait()
                yield {'event':'on_custom_event','name':'agent_event','data':{'version':1,'kind':'commentary','text':'fixture complete'}}
            async def aget_state(self,config):
                return SimpleNamespace(values={'final_reply':'持久化恢复校验答案'},next=(),tasks=())
        config=api.run_service.config(run)
        ticket=await admission.acquire(uid); tickets.append(ticket)
        delivery=StreamDelivery(db,admission,RunRepository(db))
        delivery.start(run['run_id'],run['execution_token'],api._stream_source(Graph(),{},cid,uid,config),ticket)
        await ready.wait()
        reader=delivery.follow(run['run_id'],run['execution_token'])
        first=await anext(reader); cursor=int(first.split('\n')[0][3:]); await reader.aclose()
        check('disconnect_keeps_run_running',(await RunRepository(db).get(run['run_id']))['status']=='running')
        release.set(); await asyncio.wait_for(asyncio.gather(*list(delivery.tasks.values())),10)
        check('disconnected_run_settles_once',await db.fetch_val("SELECT COUNT(*) FROM ai_message WHERE conversation_id=:cid AND role='assistant'",{'cid':cid})==1)
        restored=StreamDelivery(db,admission,RunRepository(db))
        frames=''.join([f async for f in restored.follow(run['run_id'],run['execution_token'],cursor)])
        check('new_delivery_instance_replays_persisted_result','持久化恢复校验答案' in frames and '[DONE]' in frames and len(graph_calls)==1)
        await db.execute('DELETE FROM agent_stream_frame WHERE run_id=:rid',{'rid':run['run_id']})
        fallback=''.join([f async for f in restored.follow(run['run_id'],run['execution_token'])])
        check('retained_ledger_recovers_after_event_retention','持久化恢复校验答案' in fallback and len(graph_calls)==1)

        # Restrict candidate discovery to a fixture so no real memory job is claimed.
        jobid='f'*32+uuid4().hex
        await db.execute("""INSERT INTO agent_background_job (job_id,kind,user_id,payload,status,attempts,lease_token,lease_until)
            VALUES (:id,'memory_index',:uid,'{}','running',1,'old',TIMESTAMPADD(SECOND,-1,UTC_TIMESTAMP(6)))""",{'id':jobid,'uid':uid})
        class FixtureDB:
            def __getattr__(self,name): return getattr(db,name)
            async def fetch_all(self,query,*args,**kwargs):
                if 'SELECT job_id FROM agent_background_job' in query:
                    return await db.fetch_all('SELECT job_id FROM agent_background_job WHERE job_id=:id',{'id':jobid})
                return await db.fetch_all(query,*args,**kwargs)
        jobs=DurableJobs(FixtureDB()); claimed=await jobs.claim()
        check('expired_job_is_reclaimed_with_new_fence',claimed['lease_token']!='old' and claimed['attempts']==2)
        try: await jobs.assert_lease({'job_id':jobid,'lease_token':'old'})
        except LeaseLost: check('old_worker_cannot_commit',True)
        else: check('old_worker_cannot_commit',False)
        await jobs.complete(claimed)
        check('recovered_worker_completes',await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id',{'id':jobid})=='completed')
        status=await Operations(db).readiness()
        check('real_dependency_readiness',status['status']=='ready',dependencies=status['dependencies'])
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if delivery: await delivery.shutdown()
        for ticket in tickets: await ExecutionAdmission(db).release(ticket)
        if created:
            owner=await db.fetch_val('SELECT email FROM user_info WHERE user_id=:uid',{'uid':uid})
            if owner!=marker: raise RuntimeError('fixture identity changed; refusing cleanup')
            await db.execute('DELETE f FROM agent_stream_frame f JOIN agent_run r ON r.run_id=f.run_id WHERE r.user_id=:uid',{'uid':uid})
            for table in ('agent_execution_lease','agent_background_job','agent_run'):
                await db.execute(f'DELETE FROM {table} WHERE user_id=:uid',{'uid':uid})
            await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:marker',{'uid':uid,'marker':marker})
            from app import main as api
            await api.conversation_service.invalidate_cache(cid)
            await api.conversation_service._redis.client.aclose()
            report['cleanup_complete']=True
        output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        await db.disconnect()
    if not all(c['passed'] for c in report['checks']): raise RuntimeError('fault checks failed')
    print(str(output),flush=True)


if __name__=='__main__': asyncio.run(main())
