"""Gateway -> Java -> RPC -> Python feedback check, with disposable accounts only."""
import asyncio,json,secrets,sys
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.services.conversation import ConversationService

async def main():
    ids=[(1<<57)+secrets.randbits(48) for _ in range(3)]
    # The actual login upgrades this disposable legacy fixture to the application's hash.
    password='Qa-feedback-'+secrets.token_hex(12)
    suffix=secrets.token_hex(6);rid=str(uuid4());cid=None;clients=[];checks={}
    async def call(client,method,path,body=None,expected=200):
        response=await client.request(method,path,**({'json':body} if body is not None else {}));value=response.json()
        assert value.get('code')==expected,(method,path,response.status_code,value.get('code'))
        return value.get('data')
    await db.connect()
    try:
        for n,(uid,role) in enumerate(zip(ids,[1,2,4])):
            email=f'feedback-qa-{n}-{suffix}@example.invalid'
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                VALUES(:uid,:name,:email,:password,'Disposable feedback QA',NOW(),1,2,0,0,0,1,:role,0,0,'evaluation')''',
                {'uid':uid,'name':f'反馈验收{n}-{suffix}','email':email,'password':password,'role':role})
            client=httpx.AsyncClient(base_url='http://127.0.0.1:8090/api',timeout=30,trust_env=False);clients.append(client)
            login=await call(client,'POST','/auth/login',{'email':email,'password':password});client.headers['Authorization']='Bearer '+login['token']
        owner,admin,operator=clients
        service=ConversationService();cid=await service.create_conversation(ids[0])
        mid=await service.add_message(cid,'user','临时网关验收问题',postprocess=False)
        await db.execute('''INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,result_json,data_source)
            VALUES(:rid,:cid,:uid,:rid,:hash,:token,'succeeded',UTC_TIMESTAMP(6),CAST(:result AS JSON),'evaluation')''',
            {'rid':rid,'cid':cid,'uid':ids[0],'hash':'b'*64,'token':str(uuid4()),'result':json.dumps({'user_message_id':str(mid)})})
        await service.add_message(cid,'assistant','临时网关验收回答',postprocess=False,run_id=rid)
        await call(owner,'PUT',f'/agent/runs/{rid}/feedback',{'rating':'problem','reason':'citation','comment':'临时补充说明'})
        await call(owner,'GET',f'/admin/agent-feedback/{rid}',expected=403)
        report=await call(operator,'GET','/admin/agent-feedback?source=evaluation');assert any(r['run_id']==rid for r in report['rows'])
        await call(operator,'GET',f'/admin/agent-feedback/{rid}',expected=403);checks['metadata_permission_does_not_expose_messages']=True
        detail=await call(admin,'GET',f'/admin/agent-feedback/{rid}')
        assert detail['question']['content']=='临时网关验收问题' and detail['answer']['content']=='临时网关验收回答';checks['reported_turn_loaded_through_gateway_and_rpc']=True
        edit={'state':'resolved','note':'临时网关验收完成','version':detail['feedback']['review_version'],'generation':detail['feedback']['feedback_generation'],'commandId':str(uuid4())}
        await call(operator,'PUT',f'/admin/agent-feedback/{rid}/review',edit,expected=403)
        await call(admin,'PUT',f'/admin/agent-feedback/{rid}/review',edit);await call(admin,'PUT',f'/admin/agent-feedback/{rid}/review',edit)
        updated=await call(admin,'GET',f'/admin/agent-feedback/{rid}');assert updated['feedback']['review_state']=='resolved' and len(updated['history'])==1
        checks['review_and_idempotent_retry_through_gateway']=True
        await call(owner,'PUT',f'/agent/runs/{rid}/feedback',{'rating':'problem','reason':'incorrect','comment':'重新反馈'})
        await call(admin,'PUT',f'/admin/agent-feedback/{rid}/review',{**edit,'commandId':str(uuid4())},expected=409);checks['stale_review_rejected_through_rpc']=True
    finally:
        for client in clients:
            try:await client.post('/auth/logout',headers={'X-Auth-Refresh':'1'})
            finally:await client.aclose()
        async with db.transaction():
            await db.execute('DELETE FROM agent_feedback_review_log WHERE run_id=:rid',{'rid':rid})
            await db.execute('DELETE FROM agent_admin_audit WHERE target=:rid',{'rid':rid})
            await db.execute('DELETE FROM agent_answer_feedback WHERE run_id=:rid',{'rid':rid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid',{'rid':rid})
            if cid:
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':ids[0]})
            for uid in ids:await db.execute("DELETE FROM user_info WHERE user_id=:uid AND email LIKE :email",{'uid':uid,'email':f'feedback-qa-%-{suffix}@example.invalid'})
        await db.disconnect();checks['temporary_fixture_cleaned']=True
    print(json.dumps(checks,indent=2));(ROOT/'logs/feedback-review-http-smoke.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
