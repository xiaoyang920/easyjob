"""Real local Java/MySQL message idempotency, identity and cursor regression."""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    if db.url.hostname not in {'localhost','127.0.0.1','::1'}: raise RuntimeError('local fixtures only')
    ids=SnowflakeGenerator(worker_id=27); uids=[ids.next_id(),ids.next_id()]
    marker=uuid4().hex; emails={uid:f'message-{marker}-{i}@sample.invalid' for i,uid in enumerate(uids)}
    cid=None; checks=[]; created=[]
    def check(name,condition,**details):
        item={'name':name,'passed':bool(condition),**details}; checks.append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
        if not condition: raise AssertionError(name)
    async def request(client,method,path,**kwargs):
        response=await client.request(method,path,**kwargs); response.raise_for_status(); return response.json()
    await db.connect()
    try:
        for i,uid in enumerate(uids):
            await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,
                total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)""",
                {'uid':uid,'name':f'私信验证{i}','email':emails[uid],'marker':marker})
            created.append(uid)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',headers={'Authorization':'Bearer '+local_token(uids[0])},trust_env=False,timeout=20) as sender, \
                   httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',headers={'Authorization':'Bearer '+local_token(uids[1])},trust_env=False,timeout=20) as recipient:
            conv=await request(sender,'POST','/chat/conversation/create',json={'targetUserId':str(uids[1])})
            if conv.get('code')!=200: raise RuntimeError('fixture conversation creation failed')
            cid=conv['data']['conversationId']; key=str(uuid4())
            payload={'conversationId':cid,'messageType':1,'content':'fixture message','clientMessageId':key,'senderName':'forged identity'}
            responses=await asyncio.gather(*(request(sender,'POST','/chat/message/send',json=payload) for _ in range(10)))
            mids={r['data']['messageId'] for r in responses if r.get('code')==200}
            check('ten_concurrent_retries_create_one_message',len(mids)==1 and len([r for r in responses if r.get('code')==200])==10)
            mid=next(iter(mids))
            check('sender_identity_is_backend_authoritative',all(r['data']['senderName']=='私信验证0' for r in responses))
            count=await db.fetch_val('SELECT COUNT(*) FROM message WHERE conversation_id=:cid',{'cid':int(cid)})
            unread=await db.fetch_val('SELECT unread_count FROM conversation_member WHERE conversation_id=:cid AND user_id=:uid',{'cid':int(cid),'uid':uids[1]})
            check('idempotent_retry_does_not_increment_unread_again',count==1 and unread==1,count=count,unread=unread)
            changed=await request(sender,'POST','/chat/message/send',json={**payload,'content':'changed'})
            check('same_key_different_content_returns_conflict',changed.get('code')==409)
            # Insert distinct messages through production service and paginate both directions.
            for i in range(5):
                response=await request(sender,'POST','/chat/message/send',json={**payload,'content':f'fixture {i}','clientMessageId':str(uuid4())})
                if response.get('code')!=200: raise RuntimeError('message write failed')
            recent=await request(recipient,'GET','/chat/messages',params={'conversationId':cid,'size':2})
            rows=recent['data']['records']
            check('history_page_excludes_has_more_sentinel',len(rows)==2 and recent['data']['hasMore'])
            earlier=await request(recipient,'GET','/chat/messages',params={'conversationId':cid,'size':2,'lastMessageId':rows[-1]['messageId']})
            check('history_pages_have_no_overlap',not ({r['messageId'] for r in rows}&{r['messageId'] for r in earlier['data']['records']}))
            catchup=await request(recipient,'GET','/chat/messages/after',params={'conversationId':cid,'afterMessageId':mid,'size':3})
            first=catchup['data']['records']; next_page=await request(recipient,'GET','/chat/messages/after',params={'conversationId':cid,'afterMessageId':first[-1]['messageId'],'size':3})
            recovered=first+next_page['data']['records']
            check('disconnected_client_recovers_all_missing_messages',len(recovered)==5 and len({r['messageId'] for r in recovered})==5 and [int(r['messageId']) for r in recovered]==sorted(int(r['messageId']) for r in recovered))
            await request(sender,'POST',f'/chat/message/{mid}/recall')
            replay=await request(sender,'POST','/chat/message/send',json=payload)
            check('retry_after_recall_cannot_resurrect_message',replay['data']['messageId']==mid and replay['data']['status']==1)
            limits=await request(recipient,'GET','/chat/messages',params={'conversationId':cid,'size':100000})
            check('oversized_history_page_is_rejected',limits.get('code')==400)
    finally:
        if cid:
            if await db.fetch_val('SELECT creator_id FROM conversation WHERE conversation_id=:cid',{'cid':int(cid)})!=uids[0]: raise RuntimeError('fixture owner changed')
            await db.execute('DELETE FROM message WHERE conversation_id=:cid',{'cid':int(cid)})
            await db.execute('DELETE FROM conversation_member WHERE conversation_id=:cid',{'cid':int(cid)})
            await db.execute('DELETE FROM conversation WHERE conversation_id=:cid',{'cid':int(cid)})
        for uid in created:
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email AND person_introduction=:marker',{'uid':uid,'email':emails[uid],'marker':marker})
        output=ROOT/'logs/evaluation'/f'message-delivery-{datetime.now():%Y%m%d-%H%M%S}.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({'checks':checks,'cleanup_complete':True},ensure_ascii=False,indent=2),encoding='utf-8')
        await db.disconnect()
    print(str(output),flush=True)


if __name__=='__main__': asyncio.run(main())
