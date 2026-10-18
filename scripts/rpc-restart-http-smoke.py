"""Verify gateway/RPC recovery across an actual Agent restart, without an LLM call.

Opt in with --restart-agent. Disposable account and conversation are removed.
Only the read probes are retried; no chat/save request is replayed.
"""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import subprocess
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'python-agent'))
import httpx
from app.clients.mysql_client import db
from app.services.conversation import ConversationService
from app.services.run_history import RunHistory
from app.services.run_service import RunService
from app.services.memory import memory_service
from app.services.run_repository import run_repository
from app.rpc.blog_client import close_client


async def main(restart):
    uid=(1<<57)+secrets.randbits(48)
    suffix=secrets.token_hex(6)
    email=f'rpc-restart-qa-{suffix}@example.invalid'
    password='Qa-restart-'+secrets.token_hex(12)
    cid=None;checks={};temporary_runs=[]
    await db.connect()
    conversations=ConversationService()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8090/api',timeout=20,trust_env=False) as client:
        try:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                VALUES(:uid,:name,:email,:password,'Disposable RPC restart QA',NOW(),1,2,0,0,0,1,1,0,0,'evaluation')''',
                {'uid':uid,'name':f'重连验收{suffix}','email':email,'password':password})
            login=(await client.post('/auth/login',json={'email':email,'password':password})).json()
            assert login['code']==200
            client.headers['Authorization']='Bearer '+login['data']['token']
            async def probe():
                response=await client.get('/agent/run-overview')
                return response.status_code==200 and response.json().get('code')==200
            assert await probe(),'Initial Java -> Agent RPC probe failed'
            checks['before_restart_gateway_rpc_ok']=True
            if restart:
                assert await db.fetch_val("SELECT COUNT(*) FROM agent_run WHERE status='running'")==0, 'Do not restart with active Agent runs'
                # Background services can inherit a captured pipe even after
                # PowerShell exits. A file avoids waiting for those services to
                # close stdout before subprocess.run can return.
                with (ROOT/'logs/rpc-restart-helper.log').open('wb') as helper_log:
                    result=await asyncio.to_thread(subprocess.run,
                        ['powershell','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/restart-agent.ps1')],
                        cwd=ROOT,stdout=helper_log,stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,timeout=120)
                assert result.returncode==0,'Agent restart helper failed; check service logs'
                checks['actual_agent_restart_completed']=True
            started=monotonic();failures=0
            while not await probe():
                failures+=1
                if monotonic()-started>20:
                    raise AssertionError('Java did not recover its Agent connection after restart')
                await asyncio.sleep(.3)
            checks.update(failed_read_probes=failures,recovered_in_ms=round((monotonic()-started)*1000))
            assert all([await probe() for _ in range(3)])
            checks['subsequent_gateway_rpc_probes_stable']=True

            cid=await conversations.create_conversation(uid)
            mid=await conversations.add_message(cid,'user','临时故障恢复验收问题',postprocess=False)
            previous=str(uuid4());temporary_runs.append(previous)
            await db.execute('''INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,result_json,data_source)
                VALUES(:rid,:cid,:uid,:rid,:hash,:token,'failed',UTC_TIMESTAMP(6),CAST(:result AS JSON),'evaluation')''',
                {'rid':previous,'cid':cid,'uid':uid,'hash':'a'*64,'token':str(uuid4()),
                 'result':json.dumps({'user_message_id':str(mid),'progress':{'node':'main_agent','tasks':{},'results':{}}})})
            summary,_=await RunHistory().previous(cid,uid,str(uuid4()))
            assert summary['status']=='failed' and summary['original_request']=='临时故障恢复验收问题'
            checks['real_failed_run_context_loaded']=True
            # Exercise the same application preparation used by ChatStream,
            # including real MySQL, prior failures and memory loading. Stop at
            # model admission: this test does not spend any model allowance.
            from types import SimpleNamespace
            request=SimpleNamespace(user_id=uid,conversation_id=cid,origin_article_id=None,
                message='继续',image_paths=[],request_id=uuid4())
            service=RunService(conversations,memory_service)
            _,config,state=await service.prepare_chat(request,None)
            temporary_runs.append(config['configurable']['run_id'])
            assert state['previous_run']['status']=='failed' and state['user_message']=='继续'
            await run_repository.fail(config['configurable']['run_id'],config['configurable']['execution_token'])
            checks['continue_after_failed_run_prepares_without_llm']=True
        finally:
            if cid:
                rows=await db.fetch_all('SELECT run_id FROM agent_run WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
                for row in rows:
                    rid=row._mapping['run_id']
                    await db.execute('DELETE FROM agent_run_event WHERE run_id=:rid',{'rid':rid})
                    await db.execute('DELETE FROM agent_stream_frame WHERE run_id=:rid',{'rid':rid})
                await conversations.invalidate_cache(cid)
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
                await db.execute('DELETE FROM agent_run WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
            await client.post('/auth/logout',headers={'X-Auth-Refresh':'1'})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid',{'uid':uid})
            await conversations._redis.client.aclose()
            await close_client()
            await db.disconnect()
    checks['temporary_fixture_cleaned']=True
    checks['live_llm_calls']=0
    (ROOT/'logs/rpc-restart-http-smoke.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--restart-agent',action='store_true')
    asyncio.run(main(parser.parse_args().restart_agent))
