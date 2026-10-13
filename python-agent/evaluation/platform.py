"""Real local/disposable CI HTTP+SQL checks; no Agent model generation.
python -m evaluation.platform [--seed-browser | --cleanup]
"""
import argparse,asyncio,json,secrets,os
from pathlib import Path
from uuid import uuid4
import httpx
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.fixture_cleanup import revoke_sessions

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'temp/platform-browser-fixture.json'
API=os.getenv('EASYJOB_TEST_API','http://127.0.0.1:8080')

async def cleanup(f):
    ids=[str(u['id']) for u in f['users']]
    # Preflight every identity before deleting any data.
    for u in f['users']:
        email=await db.fetch_val('SELECT email FROM user_info WHERE user_id=:id',{'id':u['id']})
        assert email is None or email==u['email'],'Fixture user identity changed'
        articles=await db.fetch_all("SELECT title FROM article_info WHERE user_id=:id UNION ALL SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.title')) AS title FROM article_revision WHERE author_id=:id",{'id':u['id']})
        assert all(a['title'].startswith(f['marker']) for a in articles),'Unexpected article on fixture user'
    # Mark articles deleted through the business endpoint before physical cleanup.
    async with httpx.AsyncClient(base_url=API,timeout=20,trust_env=False) as client:
        for u in f['users']:
            active=await db.fetch_all('SELECT article_id FROM article_info WHERE user_id=:id AND deleted=0 UNION SELECT article_id FROM article_revision WHERE author_id=:id AND deleted=0',{'id':u['id']})
            if not active:continue
            result=(await client.post('/api/auth/login',json={'email':u['email'],'password':f['password']})).json()
            assert result['code']==200,'Fixture cleanup login failed'
            token=result['data']['token'];client.cookies.clear()
            for a in active:
                result=(await client.delete('/api/article/'+str(a['article_id']),headers={'Authorization':'Bearer '+token})).json()
                assert result['code']==200,'Fixture article cleanup failed'
    for u in f['users']:
        articles=await db.fetch_all("SELECT article_id,title FROM article_info WHERE user_id=:id UNION SELECT article_id,JSON_UNQUOTE(JSON_EXTRACT(payload,'$.title')) AS title FROM article_revision WHERE author_id=:id",{'id':u['id']})
        for a in articles:
            assert a['title'].startswith(f['marker']),'Unexpected article on fixture user'
            async with db.connection() as connection:
                lock='easyjob_rag_'+str(a['article_id'])
                assert await connection.fetch_val('SELECT GET_LOCK(:name,10)',{'name':lock})==1,'Fixture index worker still busy'
                try:
                    for table in ['article_review_log','article_revision','article_index_outbox','article_view_sync','article_read_receipt','reading_session','article_tag_relation','notification','recommendation_feedback']:
                        await connection.execute(f'DELETE FROM {table} WHERE article_id=:id',{'id':a['article_id']})
                    await connection.execute('DELETE FROM article_info WHERE article_id=:id',{'id':a['article_id']})
                    if os.getenv('EASYJOB_CI')!='1':
                        from app.clients.es_client import BaseEsClient
                        es=BaseEsClient()
                        try:
                            if await es.client.indices.exists(index='article'):await es.client.delete_by_query(index='article',query={'ids':{'values':[str(a['article_id'])]}},refresh=True)
                            if await es.client.indices.exists(index='article_vectors'):await es.client.delete_by_query(index='article_vectors',query={'term':{'article_id':str(a['article_id'])}},refresh=True)
                        finally:await es.client.close()
                finally:await connection.fetch_val('SELECT RELEASE_LOCK(:name)',{'name':lock})
        for table in ['recommendation_feedback','notification','user_reading_daily','user_reading_progress']:
            await db.execute(f'DELETE FROM {table} WHERE user_id=:id',{'id':u['id']})
        runs=await db.fetch_all('SELECT run_id FROM agent_run WHERE user_id=:id',{'id':u['id']})
        for run in runs:await db.execute('DELETE FROM agent_run_event WHERE run_id=:id',{'id':run['run_id']})
        await db.execute('DELETE FROM agent_run WHERE user_id=:id',{'id':u['id']})
        await db.execute('DELETE FROM ai_conversation WHERE user_id=:id',{'id':u['id']})
        await db.execute('DELETE FROM admin_operation_log WHERE admin_user_id=:id',{'id':u['id']})
        await db.execute('DELETE FROM user_info WHERE user_id=:id AND email=:email',{'id':u['id'],'email':u['email']})
    await revoke_sessions(ids)
    for cid in f.get('categories',[]):
        assert (await db.fetch_val('SELECT category_name FROM category WHERE category_id=:id',{'id':cid})).startswith(f['marker'])
        assert not await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE category_id=:id',{'id':cid})
        await db.execute('DELETE FROM category WHERE category_id=:id',{'id':cid})

async def run(args):
    assert db.url.hostname in {'127.0.0.1','localhost','::1'},'Only local/disposable CI DB'
    assert httpx.URL(API).host in {'127.0.0.1','localhost','::1'},'Only local/disposable CI API'
    await db.connect()
    if args.cleanup:
        try:await cleanup(json.loads(MANIFEST.read_text(encoding='utf-8')));MANIFEST.unlink();print('Browser fixtures cleaned')
        finally:await db.disconnect()
        return
    assert not MANIFEST.exists(),'Clean previous browser fixtures first'
    generator=SnowflakeGenerator(worker_id=25);marker='platform-'+uuid4().hex[:10];password=secrets.token_urlsafe(28)
    f={'marker':marker,'password':password,'users':[],'categories':[],'articles':[]}
    checks=[]
    async with httpx.AsyncClient(base_url=API,timeout=20,trust_env=False) as client:
        async def call(method,path,user=None,body=None,expected=200):
            response=await client.request(method,path,json=body,headers={'Authorization':'Bearer '+user['token']} if user else {})
            value=response.json();assert value['code']==expected,(method,path,value.get('code'),value.get('message'));return value.get('data')
        async def login(user):
            client.cookies.clear();result=await call('POST','/api/auth/login',body={'email':user['email'],'password':password});user['token']=result['token'];client.cookies.clear()
        try:
            for key,role in [('admin',2),('reviewer',3),('operator',4),('reader',1),('author',1)]:
                u={'key':key,'id':generator.next_id(),'email':f'{marker}-{key}@example.invalid','name':key+'-'+marker[-10:],'role':role}
                await db.execute("INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count,data_source) VALUES (:id,:name,:email,:password,NOW(),2,1,0,0,1,:role,0,0,0,'evaluation')",{**{k:u[k] for k in ['id','name','email','role']},'password':password});f['users'].append(u);await login(u)
            admin,reviewer,operator,reader,author=f['users']
            for user,allowed,denied in [(reviewer,['/api/admin/reviews','/api/admin/articles'],['/api/admin/users','/api/admin/categories','/api/admin/agent-metrics']), (operator,['/api/admin/categories','/api/admin/operations','/api/admin/agent-metrics'],['/api/admin/users','/api/admin/reviews']), (reader,[],['/api/admin/me','/api/admin/articles','/api/admin/statistics'])]:
                for path in allowed:await call('GET',path,user)
                for path in denied:await call('GET',path,user,expected=403)
                checks.append(user['key']+' server permissions enforced')
            for user in [admin,reviewer,operator]:
                me=await call('GET','/api/admin/me',user);assert 'overview.read' in me['permissions']
                if user!=admin:assert 'users.manage' not in me['permissions']
            await call('POST','/api/admin/categories',reviewer,{'categoryName':marker},403)
            category=await call('POST','/api/admin/categories',operator,{'categoryName':marker,'parentId':'0'});cid=int(category['categoryId']);f['categories'].append(cid)
            for owner in [author,author,reader]:
                aid=generator.next_id();f['articles'].append(str(aid))
                await db.execute("INSERT INTO article_info(article_id,user_id,title,content,summary,content_type,category_id,status,deleted,is_original,view_count,like_count,collect_count,comment_count,share_count,publish_time,create_time,update_time,data_source) VALUES (:id,:uid,:title,'<p>isolated platform fixture</p>','isolated fixture',1,:category,1,0,1,0,0,0,0,0,NOW(),NOW(),NOW(),'evaluation')",{'id':aid,'uid':owner['id'],'title':marker+'-article-'+str(len(f['articles'])),'category':cid})
            ids=f['articles'];recommend='/api/article/recommend?page=1&size=50&categoryId='+str(cid)
            async def recommended():return {r['articleId'] for r in (await call('GET',recommend,reader))['records']}
            assert set(ids)==await recommended()
            await call('PUT','/api/recommendation/feedback/'+ids[0],reader,{'kind':'not_interested'});assert ids[0] not in await recommended() and ids[1] in await recommended()
            assert len(await call('GET','/api/recommendation/feedback',reader))==1
            assert await call('GET','/api/recommendation/feedback',author)==[]
            checks.append('article feedback changes recommendation with per-user isolation')
            await call('PUT','/api/recommendation/feedback/'+ids[0],reader,{'kind':'hide_author'});assert await recommended()=={ids[2]}
            await db.execute('UPDATE article_info SET deleted=1 WHERE article_id=:id',{'id':int(ids[0])})
            assert await recommended()=={ids[2]},'Author exclusion must survive deletion of its original article'
            await db.execute('UPDATE article_info SET deleted=0 WHERE article_id=:id',{'id':int(ids[0])})
            await call('DELETE','/api/recommendation/feedback/'+ids[0],author);assert await recommended()=={ids[2]}
            await call('DELETE','/api/recommendation/feedback/'+ids[0],reader);assert await recommended()==set(ids)
            await call('PUT','/api/recommendation/feedback/'+ids[0],reader,{'kind':'invalid'},400)
            checks.append('author exclusion, ownership protection and restore work')
            for aid in [int(ids[0])]+[generator.next_id() for _ in range(199)]:
                await db.execute("INSERT INTO recommendation_feedback(user_id,article_id,target_author_id,kind) VALUES (:uid,:aid,:author,'not_interested')",{'uid':reader['id'],'aid':aid,'author':author['id']})
            await call('PUT','/api/recommendation/feedback/'+ids[1],reader,{'kind':'not_interested'},400)
            await call('PUT','/api/recommendation/feedback/'+ids[0],reader,{'kind':'hide_author'})
            assert len(await call('GET','/api/recommendation/feedback',reader))==200
            await db.execute('DELETE FROM recommendation_feedback WHERE user_id=:uid',{'uid':reader['id']})
            checks.append('200-record cap permits updates but prevents extra feedback')
            draft=await call('POST','/api/article/create',author,{'title':marker+'-review','content':'<p>review fixture</p>','categoryId':str(cid),'status':1});f['pendingArticle']=draft['articleId']
            assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE article_id=:id',{'id':int(draft['articleId'])})==0
            revision=await db.fetch_val('SELECT revision_id FROM article_revision WHERE article_id=:id AND is_current=1 AND state=1',{'id':int(draft['articleId'])})
            assert revision is not None,'Submitted draft must have a current pending revision'
            await call('POST','/api/admin/reviews/'+str(revision),operator,{'decision':'approve'},403)
            if not args.seed_browser:await call('POST','/api/admin/reviews/'+str(revision),reviewer,{'decision':'reject','reason':'isolated permission check'})
            checks.append('review mutations require reviewer/admin capability')
            # Dedicated source account ensures metric checks compare a known delta against current data.
            baseline=await call('GET','/api/admin/agent-metrics?source=evaluation',operator)
            conversation=generator.next_id();await db.execute("INSERT INTO ai_conversation(conversation_id,user_id,title,status,create_time,update_time) VALUES (:cid,:uid,:title,1,NOW(),NOW())",{'cid':conversation,'uid':reader['id'],'title':marker})
            for status,elapsed,complete in [('succeeded',200,True),('succeeded',400,True),('failed',1000,False),('running',500,True)]:
                metrics={'llm_calls':2,'failed_llm_calls':int(status=='failed'),'active_duration_ms':elapsed,'measured_input_tokens':100,'measured_output_tokens':20,'token_usage_complete':complete}
                await db.execute("INSERT INTO agent_run(run_id,conversation_id,user_id,request_id,input_hash,execution_token,status,deadline,result_json,data_source) VALUES (:rid,:cid,:uid,:req,:hash,:token,:status,TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP()),:result,'evaluation')",{'rid':str(uuid4()),'cid':conversation,'uid':reader['id'],'req':str(uuid4()),'hash':'0'*64,'token':str(uuid4()),'status':status,'result':json.dumps({'metrics':metrics})})
            report=await call('GET','/api/admin/agent-metrics?source=evaluation',operator)
            assert report['totalRuns']==baseline['totalRuns']+4 and report['finishedRuns']==baseline['finishedRuns']+3
            assert report['succeededRuns']==baseline['succeededRuns']+2 and report['measuredInputTokens']==baseline['measuredInputTokens']+400
            assert report['llmCalls']==baseline['llmCalls']+8 and report['completeUsageRuns']==baseline['completeUsageRuns']+3
            assert report['latencySamples']==baseline['latencySamples']+3 and len(report['daily'])==7
            if baseline['latencySamples']==0:assert report['activeP50Ms']==400 and report['activeP95Ms']==1000
            await call('GET','/api/admin/agent-metrics?days=365',operator,expected=400)
            checks.append('metrics source, terminal denominator, measured usage and duration samples match SQL fixtures')
            # Change through the real admin editing endpoint; old access token must become unusable.
            detail=await call('GET',f"/api/admin/users/{reader['id']}",admin)
            expected={k:detail.get(k) for k in ['nickName','personIntroduction','role','status']}
            await call('PUT',f"/api/admin/users/{reader['id']}",admin,{'expectedProfile':expected,'nickName':reader['name'],'personIntroduction':detail.get('personIntroduction'),'role':4,'status':1,'reason':'isolated role revocation test'})
            await call('GET','/api/admin/me',reader,expected=401);await login(reader);assert 'metrics.read' in (await call('GET','/api/admin/me',reader))['permissions']
            await db.execute('UPDATE user_info SET role=1,auth_version=auth_version+1 WHERE user_id=:id',{'id':reader['id']});await login(reader)
            checks.append('role grant revokes old login and takes effect only after reauthentication')
            if args.seed_browser:
                MANIFEST.parent.mkdir(exist_ok=True);MANIFEST.write_text(json.dumps({**f,'users':[{k:v for k,v in u.items() if k!='token'} for u in f['users']]},ensure_ascii=False),encoding='utf-8')
        finally:
            if not args.seed_browser or not MANIFEST.exists():await cleanup(f)
            await db.disconnect()
    report={'passed':len(checks),'checks':checks,'scope':'real HTTP/MySQL, isolated fixtures; no Agent model generation'}
    (ROOT/'temp/platform-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--seed-browser',action='store_true');parser.add_argument('--cleanup',action='store_true');asyncio.run(run(parser.parse_args()))
