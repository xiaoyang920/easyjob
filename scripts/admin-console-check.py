"""Real local admin permissions, state transitions, audit and concurrency regression.

Creates disposable identities/articles; --preview holds them for UI checks then cleans up.
"""
import asyncio,json,sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient
from app.config import settings
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token

async def main():
    assert db.url.hostname in {'127.0.0.1','localhost','::1'} and settings.ES_HOST in {'127.0.0.1','localhost','::1'}
    ids=SnowflakeGenerator(worker_id=25)
    admin,author,category,article,draft,deleted=[ids.next_id() for _ in range(6)]
    marker='admin-'+uuid4().hex[:10]
    preview_password='LocalAdminQa2026!'
    email=marker+'@sample.invalid'
    output=ROOT/'logs/evaluation'/f'admin-console-{datetime.now():%Y%m%d-%H%M%S}.json'
    report={'checks':[],'scope':'local real HTTP/MySQL; isolated fixtures; no LLM calls','cleanup_complete':False}
    def check(name,passed):
        item={'name':name,'passed':bool(passed)};report['checks'].append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
        assert passed,name
    async def call(client,method,path,expected=200,**kwargs):
        response=await client.request(method,path,**kwargs);body=response.json()
        code=response.status_code if response.status_code!=200 else body.get('code')
        if code!=expected:raise RuntimeError(f'{path}: expected {expected}, got {code}: {body.get("message")}')
        return body.get('data')
    def client(uid=None):return httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30,headers={'Authorization':'Bearer '+local_token(uid)} if uid else {})
    await db.connect()
    try:
        for uid in [admin,author]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,:password,:marker,NOW(),2,1,0,0,1,:role,:count,0,0)''',
                {'uid':uid,'name':('管理' if uid==admin else '作者')+str(uid)[-8:],'email':email if uid==admin else marker+'-author@sample.invalid',
                 'password':preview_password,'marker':marker,'role':2 if uid==admin else 1,'count':1 if uid==author else 0})
        await db.execute('INSERT INTO category(category_id,category_name,parent_id,description,article_count,status,create_time,update_time) VALUES(:id,:marker,0,:marker,0,1,NOW(),NOW())',{'id':category,'marker':marker})
        for aid in [article,draft,deleted]:
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,category_id,view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,publish_time,create_time,update_time,deleted,required_level)
                VALUES(:id,:uid,:title,'管理后台测试样例','<p>正文不应出现在管理列表</p>',1,:cat,0,0,0,0,0,:status,0,0,1,NOW(),NOW(),NOW(),:deleted,1)''',
                {'id':aid,'uid':author,'title':marker+(' · 阅读成长与文章权限' if aid==article else ' · 草稿' if aid==draft else ' · 已删除'),
                 'cat':category,'status':0 if aid==draft else 1,'deleted':1 if aid==deleted else 0})
        async with client() as guest,client(author) as ordinary,client(admin) as manager:
            await call(guest,'GET','/admin/me',401);check('guest_requires_login',True)
            for path in ['/admin/me','/admin/overview','/admin/articles','/admin/users','/admin/logs']:
                await call(ordinary,'GET',path,403)
            check('ordinary_user_cannot_read_any_admin_endpoint',True)
            await call(ordinary,'PUT',f'/admin/articles/{article}/reading-level',403,json={'expectedLevel':1,'level':2})
            await call(ordinary,'PUT',f'/admin/articles/{article}/visibility',403,json={'expectedStatus':1,'status':2})
            check('ordinary_user_cannot_mutate_admin_state',True)
            await db.execute('UPDATE user_info SET status=0 WHERE user_id=:uid',{'uid':admin})
            await call(manager,'GET','/admin/me',403);check('disabled_administrator_is_denied',True)
            await db.execute('UPDATE user_info SET status=1 WHERE user_id=:uid',{'uid':admin})
            check('administrator_identity_uses_string_id',(await call(manager,'GET','/admin/me'))['userId']==str(admin))
            overview=await call(manager,'GET','/admin/overview');check('overview_includes_growth_rules',len(overview['rules'])==5 and overview['published']>=1)
            rows=await call(manager,'GET','/admin/articles',params={'keyword':marker})
            check('article_search_excludes_deleted_and_preserves_drafts',rows['total']==2 and {r['articleId'] for r in rows['records']}=={str(article),str(draft)})
            check('article_list_never_exposes_body','正文不应' not in json.dumps(rows,ensure_ascii=False) and all('content' not in r for r in rows['records']))
            check('literal_wildcard_does_not_match_everything',(await call(manager,'GET','/admin/articles',params={'keyword':marker+'%'}))['total']==0)
            for path,params in [('/admin/articles',{'status':99}),('/admin/users',{'page':0}),('/admin/logs',{'size':101})]:await call(manager,'GET',path,400,params=params)
            check('invalid_filters_and_pagination_rejected',True)
            user_rows=await call(manager,'GET','/admin/users',params={'keyword':str(author)})
            check('users_can_be_found_by_exact_id',user_rows['total']==1 and user_rows['records'][0]['userId']==str(author))
            check('user_status_is_numeric_and_normal',type(user_rows['records'][0]['status']) is int and user_rows['records'][0]['status']==1)
            check('user_list_has_no_password_or_email',all('password' not in r and 'email' not in r for r in user_rows['records']))
            await call(manager,'PUT',f'/admin/articles/{article}/reading-level',json={'expectedLevel':1,'level':2})
            check('level_change_is_persisted',await db.fetch_val('SELECT required_level FROM article_info WHERE article_id=:id',{'id':article})==2)
            await call(manager,'PUT',f'/admin/articles/{article}/reading-level',409,json={'expectedLevel':1,'level':3})
            await call(manager,'PUT',f'/admin/articles/{article}/reading-level',400,json={'expectedLevel':2,'level':99})
            check('stale_and_invalid_level_changes_cannot_overwrite',await db.fetch_val('SELECT required_level FROM article_info WHERE article_id=:id',{'id':article})==2)
            await call(manager,'PUT',f'/admin/articles/{draft}/visibility',409,json={'expectedStatus':0,'status':1});check('moderation_cannot_publish_drafts',True)
            publish_time=await db.fetch_val('SELECT publish_time FROM article_info WHERE article_id=:id',{'id':article})
            await call(manager,'PUT',f'/admin/articles/{article}/visibility',json={'expectedStatus':1,'status':2})
            check('takedown_is_separate_from_draft',await db.fetch_val('SELECT status FROM article_info WHERE article_id=:id',{'id':article})==2)
            check('takedown_decrements_published_count',await db.fetch_val('SELECT article_count FROM user_info WHERE user_id=:id',{'id':author})==0)
            await call(guest,'GET',f'/article/detail/{article}',404);check('takedown_blocks_public_detail_even_with_cache',True)
            await call(manager,'PUT',f'/admin/articles/{article}/visibility',json={'expectedStatus':2,'status':1})
            check('restore_preserves_publish_time_and_level',await db.fetch_val('SELECT publish_time FROM article_info WHERE article_id=:id',{'id':article})==publish_time and await db.fetch_val('SELECT required_level FROM article_info WHERE article_id=:id',{'id':article})==2)
            check('restore_increments_count_once',await db.fetch_val('SELECT article_count FROM user_info WHERE user_id=:id',{'id':author})==1)
            await call(manager,'PUT',f'/admin/articles/{article}/visibility',409,json={'expectedStatus':2,'status':1});check('stale_restore_rejected',True)
            responses=await asyncio.gather(*(manager.put(f'/admin/articles/{article}/visibility',json={'expectedStatus':1,'status':2}) for _ in range(10)))
            codes=[r.json()['code'] for r in responses]
            check('concurrent_takedown_commits_one_transition',codes.count(200)==1 and codes.count(409)==9 and await db.fetch_val('SELECT article_count FROM user_info WHERE user_id=:id',{'id':author})==0)
            logs=await db.fetch_all('SELECT action,before_value,after_value FROM admin_operation_log WHERE target_id=:id',{'id':article})
            check('only_committed_changes_are_audited',len(logs)==4)
            api_logs=await call(manager,'GET','/admin/logs');check('audit_list_contains_committed_change',any(r['targetId']==str(article) for r in api_logs['records']))
            await call(manager,'PUT',f'/admin/articles/{article}/visibility',json={'expectedStatus':2,'status':1})
            if '--preview' in sys.argv:
                print(f'Preview login: {email} / {preview_password}',flush=True)
                print(f'Preview search: {marker}',flush=True)
                await asyncio.to_thread(input,'Press Enter after browser QA to clean up fixtures. ')
    finally:
        for uid in [admin,author]:
            if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})!=1:continue
            await db.execute('DELETE FROM admin_operation_log WHERE admin_user_id=:uid',{'uid':uid})
            for aid in [article,draft,deleted]:
                await db.execute('DELETE FROM article_index_outbox WHERE article_id=:id',{'id':aid})
                await db.execute('DELETE FROM article_read_receipt WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM article_info WHERE user_id=:uid AND category_id=:cat',{'uid':uid,'cat':category})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})
        await db.execute('DELETE FROM category WHERE category_id=:id AND category_name=:marker',{'id':category,'marker':marker})
        es=BaseEsClient().client
        try:
            await es.delete_by_query(index='article',query={'ids':{'values':[str(a) for a in [article,draft,deleted]]}},refresh=True,conflicts='proceed')
            await es.delete_by_query(index='article_vectors',query={'terms':{'article_id':[str(a) for a in [article,draft,deleted]]}},refresh=True,conflicts='proceed')
        finally:await es.close();await db.disconnect()
        report['cleanup_complete']=True;output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(output,flush=True)
if __name__=='__main__':asyncio.run(main())
