"""Real internal Agent gateway checks with disposable users/runs; no model calls."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'}
    ids=SnowflakeGenerator(worker_id=27)
    uid,other,cid,aid=[ids.next_id() for _ in range(4)]
    marker='qa-agent-'+uuid4().hex[:10]
    checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        print(name+': '+str(bool(value)),flush=True)
        assert value,name
    async def scalar(sql,**params):return await db.fetch_val(sql,params)
    async def request(client,method,path,code=200,**kwargs):
        response=await client.request(method,path,**kwargs)
        data=response.json()
        actual=data.get('code',response.status_code)
        assert actual==code,(path,actual,data.get('message'))
        return data.get('data',data)
    async def run(body):
        rid,token=str(uuid4()),str(uuid4())
        hasher=hashlib.sha256()
        for value in [body['title'],body['summary'],body['markdown'],body['html']]:
            raw=value.encode();hasher.update(len(raw).to_bytes(4,'big'));hasher.update(raw)
        digest=hasher.hexdigest()
        await db.execute('''INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,executor_lease_until,draft_hash)
            VALUES(:rid,:cid,:uid,:request,:input,:token,'running',UTC_TIMESTAMP(6)+INTERVAL 5 MINUTE,UTC_TIMESTAMP(6)+INTERVAL 5 MINUTE,:hash)''',
            {'rid':rid,'cid':cid,'uid':uid,'request':str(uuid4()),'input':'0'*64,'token':token,'hash':digest})
        return {**body,'runId':rid,'executionToken':token,'draftHash':digest}
    await db.connect()
    try:
        for who in [uid,other]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,role,data_source,total_coin_count,current_coin_count,theme,article_count,follower_count,following_count)
                VALUES(:id,:name,:email,'isolated-test',:marker,NOW(),2,1,1,'evaluation',0,0,1,0,0,0)''',{'id':who,'name':marker[:12]+str(who)[-6:],'marker':marker,'email':str(who)+'@sample.invalid'})
        await db.execute('INSERT INTO ai_conversation(conversation_id,user_id,title,status) VALUES(:id,:uid,:title,1)',{'id':cid,'uid':uid,'title':marker})
        headers={'X-Agent-Key':settings.AGENT_SERVICE_KEY,'X-Agent-User':str(uid)}
        async with httpx_client(headers) as internal,httpx_client({'Authorization':'Bearer '+local_token(uid)}) as owner,httpx_client({**headers,'X-Agent-User':str(other)}) as foreign:
            body={'articleId':str(aid),'title':marker,'summary':'摘要','markdown':'正文','html':'<p>正文</p><img src="/uploads/example.png">'}
            create=await run(body)
            saved=await request(internal,'POST','/internal/agent/drafts',json=create)
            check('agent_new_draft_keeps_stable_id',saved['articleId']==str(aid))
            check('agent_new_draft_has_no_info',await scalar('SELECT COUNT(*) FROM article_info WHERE article_id=:id',id=aid)==0)
            check('agent_new_draft_creates_one_revision',await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id',id=aid)==1)
            again=await request(internal,'POST','/internal/agent/drafts',json=create)
            check('approval_retry_does_not_duplicate_revision',again==saved and await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id',id=aid)==1)
            draft=await request(internal,'GET',f'/internal/agent/drafts/{aid}')
            check('private_read_returns_full_body_and_lock','/uploads/example.png' in draft['payload']['content'] and draft['lockVersion']==0)
            await request(foreign,'GET',f'/internal/agent/drafts/{aid}',404)
            check('foreign_agent_cannot_read_draft',True)
            edit={'title':marker,'summary':'编辑器修改','content':'<p>手动的新正文</p>','status':0,'contentType':1,'isOriginal':1,
                'coverImage':'/uploads/cover.png','tagNames':['Java'],'expectedRevisionId':draft['revisionId'],'expectedLockVersion':0}
            changed=await request(owner,'PUT',f'/api/article/{aid}',json=edit)
            check('manual_save_updates_same_revision',changed['revisionId']==draft['revisionId'] and changed['lockVersion']==1)
            await db.execute("UPDATE agent_run SET status='completed' WHERE run_id=:id",{'id':create['runId']})
            update=await run({**body,'title':marker+'修改','expectedRevisionId':draft['revisionId'],'expectedLockVersion':0})
            await request(internal,'POST','/internal/agent/drafts',409,json=update)
            check('stale_agent_confirmation_is_http409',True)
            check('stale_agent_confirmation_preserves_manual_body',json.loads(await scalar('SELECT payload FROM article_revision WHERE revision_id=:id',id=draft['revisionId']))['content']=='<p>手动的新正文</p>')
            current=await request(internal,'GET',f'/internal/agent/drafts/{aid}')
            update['expectedLockVersion']=current['lockVersion']
            await request(internal,'POST','/internal/agent/drafts',json=update)
            current=await request(internal,'GET',f'/internal/agent/drafts/{aid}')
            check('fresh_agent_save_preserves_article_metadata',current['payload']['coverImage']=='/uploads/cover.png' and current['payload']['tagNames']==['Java'])
            check('fresh_agent_save_reuses_revision',current['revisionId']==draft['revisionId'] and current['lockVersion']==2)
            await request(internal,'POST','/internal/agent/drafts',json=update)
            check('agent_update_retry_does_not_increment_lock',(await request(internal,'GET',f'/internal/agent/drafts/{aid}'))['lockVersion']==2)
            await request(owner,'DELETE',f'/api/article/{aid}')
            await request(internal,'GET',f'/internal/agent/drafts/{aid}',404)
            check('deleted_workspace_is_not_readable',True)
            check('private_saves_never_publish_index',await scalar('SELECT COUNT(*) FROM article_index_outbox WHERE article_id=:id',id=aid)==0)
    finally:
        # Only generated IDs owned by our marked fixture are eligible for cleanup.
        if await scalar('SELECT COUNT(*) FROM user_info WHERE user_id=:id AND person_introduction=:marker',id=uid,marker=marker)==1:
            for table in ['article_review_log','article_revision','article_index_outbox']:
                await db.execute(f'DELETE FROM {table} WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM agent_run_event WHERE run_id IN(SELECT run_id FROM agent_run WHERE user_id=:id)',{'id':uid})
            await db.execute('DELETE FROM agent_run WHERE user_id=:id',{'id':uid})
            await db.execute('DELETE FROM ai_conversation WHERE conversation_id=:id AND user_id=:uid',{'id':cid,'uid':uid})
        for who in [uid,other]:
            await db.execute('DELETE FROM user_info WHERE user_id=:id AND person_introduction=:marker',{'id':who,'marker':marker})
        await db.disconnect()
        path=ROOT/'logs/evaluation'/f'agent-workspace-{datetime.now():%Y%m%d-%H%M%S}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'checks':checks,'cleanup_complete':True},ensure_ascii=False,indent=2),encoding='utf-8')
        print(path)


def httpx_client(headers):
    import httpx
    return httpx.AsyncClient(base_url='http://127.0.0.1:8080',headers=headers,trust_env=False,timeout=30)


if __name__=='__main__':asyncio.run(main())
