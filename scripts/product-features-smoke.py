"""Loopback-only disposable fixtures. No model calls or outgoing email."""
import asyncio,hashlib,json,secrets,sys
from pathlib import Path
from uuid import uuid4
import httpx,websockets
from redis.asyncio import Redis
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.services.conversation import ConversationService
from app.utils.snowflake import snowflake
from evaluation.local_samples import local_token

async def main():
    assert settings.MYSQL_HOST in ('localhost','127.0.0.1','::1')
    uid,other=snowflake.next_id(),snowflake.next_id()
    email='product-'+secrets.token_hex(8)+'@sample.invalid';password=secrets.token_urlsafe(20)
    cid=None;aid=None;chat_id=None;rid=str(uuid4());checks={};clients=[];session_ids=[]
    redis=Redis(host=settings.REDIS_HOST,port=settings.REDIS_PORT,db=settings.REDIS_DB,password=settings.REDIS_PASSWORD or None,decode_responses=True)
    await db.connect()
    async def call(client,method,path,body=None,code=200):
        response=await client.request(method,path,**({'json':body} if body is not None else {}))
        value=response.json()
        assert value.get('code')==code,(method,path,response.status_code,value.get('message'))
        return value.get('data')
    async def next_frame(socket,kind):
        async with asyncio.timeout(5):
            while True:
                value=json.loads(await socket.recv())
                if value.get('type')==kind:return value
    try:
        for id,address in [(uid,email),(other,'other-'+email)]:
            await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
                status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count)
                VALUES(:uid,:name,:email,:password,'Temporary product feature test',NOW(),1,2,0,0,0,1,1,0,0)""",
                {'uid':id,'name':'功能验收'+secrets.token_hex(5),'email':address,'password':password})
        for n in range(2):
            c=httpx.AsyncClient(base_url='http://127.0.0.1:8090/api',timeout=20,trust_env=False,headers={'User-Agent':f'Product smoke browser {n}'})
            clients.append(c)
            identity=await call(c,'POST','/auth/login',{'email':email,'password':password})
            c.headers['Authorization']='Bearer '+identity['token']
            session_ids.append(json.loads(__import__('base64').urlsafe_b64decode(identity['token'].split('.')[1]+'=='))['sid'])
        first,second=clients
        devices=await call(first,'GET','/account/sessions')
        assert len(devices)==2 and sum(d['current'] for d in devices)==1
        checks['two_owned_devices']=True
        outsider=httpx.AsyncClient(base_url='http://127.0.0.1:8090/api',timeout=20,trust_env=False,headers={'Authorization':'Bearer '+local_token(other)})
        clients.append(outsider)
        await call(outsider,'DELETE','/account/sessions/'+session_ids[0],code=404)
        checks['device_owner_isolation']=True
        cid=await ConversationService().create_conversation(uid)
        await ConversationService().add_message(cid,'user','唯一搜索词'+rid,postprocess=False)
        await db.execute("""INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,result_json,data_source)
            VALUES(:rid,:cid,:uid,:rid,:hash,:token,'succeeded',UTC_TIMESTAMP(6),'{}','evaluation')""",
            {'rid':rid,'cid':cid,'uid':uid,'hash':'a'*64,'token':str(uuid4())})
        await ConversationService().add_message(cid,'assistant','功能验收回答',postprocess=False,run_id=rid)
        library=await call(first,'GET','/agent/library?keyword='+rid)
        assert any(r['conversationId']==str(cid) for r in library['rows'])
        await call(first,'PATCH',f'/agent/conversations/{cid}',{'title':'新的对话名','pinned':True,'version':0})
        await call(first,'PATCH',f'/agent/conversations/{cid}',{'title':'过期覆盖','version':0},code=409)
        await call(outsider,'PATCH',f'/agent/conversations/{cid}',{'title':'越权','version':1},code=404)
        checks['conversation_search_pin_rename_and_conflicts']=True
        await call(first,'PUT',f'/agent/runs/{rid}/feedback',{'rating':'problem','reason':'citation','comment':'临时反馈'})
        assert (await call(first,'GET',f'/agent/runs/{rid}/feedback'))['reason']=='citation'
        await call(outsider,'PUT',f'/agent/runs/{rid}/feedback',{'rating':'helpful'},code=404)
        history=await call(first,'GET',f'/agent/conversations/{cid}/messages?limit=20')
        assert any(m.get('runId')==rid for m in history.get('items',[]) if m.get('role')=='assistant')
        checks['durable_feedback_and_message_run_association']=True
        category=await db.fetch_val('SELECT category_id FROM article_info WHERE category_id IS NOT NULL LIMIT 1')
        body={'title':'临时自动保存验收','content':'<p>正文</p>','categoryId':str(category),'contentType':1,'isOriginal':1,'status':0,'tagNames':[],'clientRequestId':str(uuid4())}
        created=await call(first,'POST','/article/create',body);aid=int(created['articleId'])
        assert created.get('revisionId') and created.get('lockVersion')==0
        retry=await call(first,'POST','/article/create',body)
        assert retry['articleId']==created['articleId']
        checks['first_save_retry_is_idempotent']=True
        version=await db.fetch_val('SELECT version_no FROM article_revision WHERE article_id=:aid',{'aid':aid})
        current=created
        for n in range(5):
            current=await call(first,'PUT',f'/article/{aid}',{**body,'title':'自动保存'+str(n),'expectedRevisionId':current['revisionId'],'expectedLockVersion':current['lockVersion']})
        assert await db.fetch_val('SELECT COUNT(*) FROM article_revision WHERE article_id=:aid',{'aid':aid})==1
        assert await db.fetch_val('SELECT version_no FROM article_revision WHERE article_id=:aid',{'aid':aid})==version
        assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE article_id=:aid',{'aid':aid})==0
        checks['repeated_saves_keep_one_draft_and_unchanged_version']=True
        tokens=[c.headers['Authorization'][7:] for c in (first,second)]
        async with websockets.connect('ws://127.0.0.1:8090/ws/chat?token='+tokens[0]) as a,websockets.connect('ws://127.0.0.1:8090/ws/chat?token='+tokens[1]) as b:
            await next_frame(a,'online_users');await next_frame(b,'online_users')
            chat=await call(first,'POST','/chat/conversation/create',{'targetUserId':str(other)});chat_id=chat['conversationId']
            sent=await call(first,'POST','/chat/message/send',{'conversationId':chat_id,'messageType':1,'content':'多端验收','clientMessageId':str(uuid4())})
            assert (await next_frame(a,'message'))['messageId']==sent['messageId']
            assert (await next_frame(b,'message'))['messageId']==sent['messageId']
            checks['sender_echo_reaches_both_tabs']=True
            await redis.publish('easyjob:chat:events:v1',json.dumps({'node':'smoke-peer-'+rid,'kind':'message','uid':str(uid),'data':json.dumps({'type':'smoke_peer'})}))
            await next_frame(a,'smoke_peer');await next_frame(b,'smoke_peer');checks['cross_node_pubsub_fanout']=True
            await call(first,'POST','/account/sessions/revoke-others')
            await asyncio.wait_for(b.wait_closed(),5)
            assert (await second.get('/account/sessions')).status_code==401
            await a.send('{"type":"ping"}');await next_frame(a,'pong')
            checks['revoke_other_device_closes_socket_keeps_current']=True
        await call(first,'PUT','/account/password',{'currentPassword':password,'newPassword':password+'new'})
        assert (await first.get('/account/sessions')).status_code==401
        assert (await first.post('/auth/refresh',headers={'X-Auth-Refresh':'1'})).json()['code']==401
        checks['password_change_revokes_access_and_refresh']=True
        # Seed only the disposable account's reset code. Do not send real email.
        code=''.join(secrets.choice('0123456789') for _ in range(6));key='auth:password-code:'+hashlib.sha256(email.encode()).hexdigest()
        await redis.set(key,hashlib.sha256((email+':'+code).encode()).hexdigest(),ex=600)
        await call(first,'POST','/auth/password/reset',{'email':email,'code':code,'password':password+'reset'})
        await call(first,'POST','/auth/password/reset',{'email':email,'code':code,'password':password+'reset'},code=400)
        checks['reset_code_is_single_use']=True
        print(json.dumps(checks,ensure_ascii=False,indent=2))
    finally:
        for c in clients:
            try:await c.post('/auth/logout',headers={'X-Auth-Refresh':'1'})
            finally:await c.aclose()
        async with db.transaction():
            if chat_id:
                await db.execute('DELETE FROM message WHERE conversation_id=:cid',{'cid':int(chat_id)})
                await db.execute('DELETE FROM conversation_member WHERE conversation_id=:cid',{'cid':int(chat_id)})
                await db.execute('DELETE FROM conversation WHERE conversation_id=:cid',{'cid':int(chat_id)})
            if aid:await db.execute('DELETE FROM article_revision WHERE article_id=:aid AND author_id=:uid',{'aid':aid,'uid':uid})
            await db.execute('DELETE FROM agent_answer_feedback WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
            await db.execute('DELETE FROM agent_run WHERE run_id=:rid AND user_id=:uid',{'rid':rid,'uid':uid})
            if cid:
                await db.execute('DELETE FROM ai_message WHERE conversation_id=:cid',{'cid':cid})
                await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid',{'cid':cid,'uid':uid})
            for id,address in [(uid,email),(other,'other-'+email)]:await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email',{'uid':id,'email':address})
        for key in [f'auth:devices:{uid}',f'auth:devices:{other}',*['auth:session:'+s for s in session_ids],*['auth:device:'+s for s in session_ids]]:await redis.delete(key)
        await redis.aclose();await db.disconnect()
        checks['temporary_fixture_cleaned']=True
        (ROOT/'logs/product-features-live.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
