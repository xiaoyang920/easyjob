"""Local category creation/permission/concurrency probe. Cleans exact fixtures; no LLM."""
import asyncio,json,os
from pathlib import Path
from uuid import uuid4
import httpx
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.fixture_cleanup import revoke_sessions

async def run():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'},'Local database only'
    await db.connect()
    marker='cat-'+uuid4().hex[:10];ids=SnowflakeGenerator(worker_id=27)
    users=[];category_ids=[];article_ids=[];checks=[]
    async with httpx.AsyncClient(base_url=os.getenv('EASYJOB_TEST_API','http://127.0.0.1:8080'),timeout=20,trust_env=False) as client:
        async def request(method,path,token=None,body=None,expected=200):
            response=await client.request(method,path,json=body,headers={'Authorization':f'Bearer {token}'} if token else {})
            result=response.json();assert result['code']==expected,(path,result.get('code'),result.get('message'))
            return result.get('data')
        async def create(name,parent='0'):
            result=await request('POST','/api/admin/categories',admin,{'categoryName':name,'parentId':parent,'sortOrder':12,'description':'isolated category probe'})
            category_ids.append(int(result['categoryId']));return result
        try:
            for role in [2,1]:
                uid=ids.next_id();email=f'{marker}-{role}@example.invalid'
                await db.execute("INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count) VALUES (:uid,:name,:email,:password,NOW(),2,1,0,0,1,:role,0,0,0)",{'uid':uid,'name':f'{marker}-{role}','email':email,'password':'Local-category-probe-2026!','role':role})
                users.append({'id':uid,'email':email})
                await db.execute("UPDATE user_info SET data_source='evaluation' WHERE user_id=:id",{'id':uid})
                client.cookies.clear()
                result=await request('POST','/api/auth/login',body={'email':email,'password':'Local-category-probe-2026!'})
                users[-1]['token']=result['token']
            admin,ordinary=users[0]['token'],users[1]['token'];client.cookies.clear()
            for method in ['GET','POST']:
                await request(method,'/api/admin/categories',ordinary,{'categoryName':marker} if method=='POST' else None,403)
            checks.append('ordinary users cannot list or create admin categories')
            for body in [{'categoryName':' '},{'categoryName':'a'*51},{'categoryName':marker,'sortOrder':-1},{'categoryName':marker,'description':'a'*201},{'categoryName':marker,'parentId':'-1'}]:
                await request('POST','/api/admin/categories',admin,body,400)
            checks.append('name, description, sorting and parent bounds rejected')
            root=await create(marker);child=await create(marker+'-child',root['categoryId'])
            assert int(root['categoryId'])>2**53 and isinstance(root['categoryId'],str)
            public=await request('GET','/api/category/list',ordinary);visible=next(r for r in public if r['categoryId']==root['categoryId'])
            assert visible['categoryName']==marker and [r['categoryId'] for r in visible['children']]==[child['categoryId']]
            await request('POST','/api/admin/categories',admin,{'categoryName':marker+'-deep','parentId':child['categoryId']},400)
            await request('POST','/api/admin/categories',admin,{'categoryName':marker+'-missing','parentId':str(ids.next_id())},400)
            checks.append('root and child immediately visible; missing parent and third level rejected')
            second=await create(marker+'-second');await create(marker+'-child',second['categoryId'])
            await request('POST','/api/admin/categories',admin,{'categoryName':marker+'-child','parentId':root['categoryId']},409)
            checks.append('same-parent name conflict; same names under different roots allowed')
            async def race():
                response=await client.post('/api/admin/categories',json={'categoryName':marker+'-race'},headers={'Authorization':f'Bearer {admin}'})
                return response.json()
            results=await asyncio.gather(*(race() for _ in range(10)))
            category_ids.extend(int(r['data']['categoryId']) for r in results if r['code']==200)
            assert sum(r['code']==200 for r in results)==1 and sum(r['code']==409 for r in results)==9
            checks.append('10 concurrent duplicate requests create exactly one category')
            audits=await db.fetch_all("SELECT target_id,details_json FROM admin_operation_log WHERE admin_user_id=:uid AND action='category_create'",{'uid':users[0]['id']})
            assert {int(r['target_id']) for r in audits}==set(category_ids) and len(audits)==len(category_ids)
            for audit in audits:assert json.loads(audit['details_json'])['categoryName'].startswith(marker)
            checks.append('one audit per successful creation and no failed-write audit')
            async def category(cid):
                return next(r for r in await request('GET','/api/admin/categories',admin) if r['categoryId']==cid)
            async def update(cid,name,status=1,version=None):
                row=await category(cid)
                response=await client.put(f'/api/admin/categories/{cid}',headers={'Authorization':f'Bearer {admin}'},json={'expectedVersion':row['version'] if version is None else version,'categoryName':name,'sortOrder':3,'description':'edited probe','status':status})
                return response.json()
            await request('PUT',f"/api/admin/categories/{root['categoryId']}",ordinary,{},403)
            await request('POST',f"/api/admin/categories/{root['categoryId']}/migrate",ordinary,{},403)
            assert (await update(root['categoryId'],marker,status=0))['code']==409
            checks.append('edit/migrate require admin; active children block parent disable')
            leaf=child['categoryId'];initial=await category(leaf)
            results=await asyncio.gather(*(update(leaf,marker+f'-edit-{i}',version=initial['version']) for i in range(2)))
            assert sorted(r['code'] for r in results)==[200,409],results
            assert (await category(leaf))['version']=='1'
            checks.append('concurrent stale category forms: one succeeds, one conflicts')
            assert (await update(leaf,marker+'-renamed',status=0))['code']==200
            public=await request('GET','/api/category/list',ordinary)
            assert not any(c['categoryId']==leaf for r in public for c in r.get('children',[]))
            assert (await update(leaf,marker+'-renamed',status=1))['code']==200
            public=await request('GET','/api/category/list',ordinary)
            assert next(c for r in public for c in r.get('children',[]) if c['categoryId']==leaf)['categoryName']==marker+'-renamed'
            checks.append('renaming/sorting/disabling immediately update public categories')
            source=await create(marker+'-source');target=await create(marker+'-target')
            for intent in [0,1]:
                created=await request('POST','/api/article/create',ordinary,{'title':marker+f'-article-{intent}','content':'<p>category migration fixture</p>','contentType':1,'categoryId':source['categoryId'],'status':intent})
                article_ids.append(int(created['articleId']))
                assert await db.fetch_val('SELECT data_source FROM article_info WHERE article_id=:id',{'id':article_ids[-1]})=='evaluation'
            pending=await db.fetch_one('SELECT revision_id,content_hash,CAST(payload AS CHAR) AS payload FROM article_revision WHERE article_id=:id AND state=1',{'id':article_ids[1]})
            await request('POST',f"/api/admin/categories/{source['categoryId']}/migrate",admin,{'expectedVersion':0,'targetId':target['categoryId'],'targetVersion':999},409)
            assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE category_id=:id',{'id':int(source['categoryId'])})==2
            moved=await request('POST',f"/api/admin/categories/{source['categoryId']}/migrate",admin,{'expectedVersion':0,'targetId':target['categoryId'],'targetVersion':0})
            assert moved['articleCount']==2 and (await category(source['categoryId']))['status']==0
            assert (await category(target['categoryId']))['version']=='1'
            assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE category_id=:id',{'id':int(target['categoryId'])})==2
            checks.append('migration is atomic with source/target versions and covers drafts/pending articles')
            for aid in article_ids:
                editor=await request('GET',f'/api/article/{aid}/edit',ordinary)
                assert editor['categoryId']==target['categoryId']
            await request('POST',f"/api/admin/reviews/{pending['revision_id']}",admin,{'decision':'approve','reason':''})
            after=await db.fetch_one('SELECT content_hash,CAST(payload AS CHAR) AS payload FROM article_revision WHERE revision_id=:id',{'id':pending['revision_id']})
            assert after['content_hash']==pending['content_hash'] and after['payload']==pending['payload']
            assert await db.fetch_val('SELECT category_id FROM article_info WHERE article_id=:id',{'id':article_ids[1]})==int(target['categoryId'])
            editor=await request('GET',f'/api/article/{article_ids[0]}/edit',ordinary)
            await request('PUT',f'/api/article/{article_ids[0]}',ordinary,{'title':marker+'-article-0','content':'<p>old editor category resolves to new target</p>','categoryId':source['categoryId'],'status':0,'expectedRevisionId':editor['revisionId']})
            assert await db.fetch_val('SELECT category_id FROM article_info WHERE article_id=:id',{'id':article_ids[0]})==int(target['categoryId'])
            assert (await update(source['categoryId'],marker+'-source',status=1))['code']==409
            checks.append('old editor/approval routes to target without rewriting immutable snapshots or reactivating source')
            cached=await request('GET',f'/api/article/detail/{article_ids[1]}',ordinary)
            assert cached['categoryName']==target['categoryName']
            assert (await update(target['categoryId'],marker+'-target-renamed'))['code']==200
            fresh=await request('GET',f'/api/article/detail/{article_ids[1]}',ordinary)
            assert fresh['categoryName']==marker+'-target-renamed'
            checks.append('category rename invalidates cached published article details after commit')
            audits=await db.fetch_all("SELECT action FROM admin_operation_log WHERE admin_user_id=:id",{'id':users[0]['id']})
            assert sum(a['action']=='category_migrate' for a in audits)==1
            checks.append('successful edit/migration audited; failed version checks leave no migration audit')
        finally:
            for aid in article_ids:
                row=await db.fetch_one('SELECT user_id,title,deleted FROM article_info WHERE article_id=:id',{'id':aid})
                assert row and row['user_id']==users[1]['id'] and row['title'].startswith(marker),'Article identity changed; refusing cleanup'
                if not row['deleted']:await request('DELETE',f'/api/article/{aid}',users[1]['token'])
                # Remove only our immutable snapshots and queued jobs; late index messages see a deleted/missing article.
                for table in ['article_review_log','article_revision','article_index_outbox','article_tag_relation','notification']:
                    await db.execute(f'DELETE FROM {table} WHERE article_id=:id',{'id':aid})
                await db.execute('DELETE FROM article_info WHERE article_id=:id AND user_id=:uid',{'id':aid,'uid':users[1]['id']})
            # Verify ownership and absence of any article use before removing exact probe categories.
            for cid in reversed(category_ids):
                name=await db.fetch_val('SELECT category_name FROM category WHERE category_id=:id',{'id':cid})
                assert name and name.startswith(marker),'Category identity changed; refusing cleanup'
                assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE category_id=:id',{'id':cid})==0,'Fixture was used; refusing cleanup'
                await db.execute("DELETE FROM admin_operation_log WHERE target_type='category' AND target_id=:id AND admin_user_id=:uid",{'id':cid,'uid':users[0]['id']})
                await db.execute('DELETE FROM category WHERE category_id=:id',{'id':cid})
            for user in users:
                assert await db.fetch_val('SELECT email FROM user_info WHERE user_id=:id',{'id':user['id']})==user['email'],'User identity changed; refusing cleanup'
                await db.execute('DELETE FROM user_info WHERE user_id=:id AND email=:email',{'id':user['id'],'email':user['email']})
            await revoke_sessions([user['id'] for user in users])
            await db.disconnect()
    print(json.dumps({'passed':len(checks),'checks':checks}))
    (Path(__file__).resolve().parents[2]/'temp/admin-categories-results.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'scope':'real local HTTP/MySQL, isolated fixtures cleaned, no agent model generation'},indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(run())
