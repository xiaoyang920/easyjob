"""Real loopback API/MySQL/ES checks using disposable authors and articles only."""
import asyncio
import json
import secrets
import sys
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
    assert db.url.hostname in {'localhost','127.0.0.1','::1'}
    assert settings.ES_HOST in {'localhost','127.0.0.1','::1'}
    ids=SnowflakeGenerator(worker_id=25)
    author,reader,admin=[ids.next_id() for _ in range(3)]
    articles=[ids.next_id() for _ in range(6)]
    redis,js,rag,locked,draft,deleted=articles
    category=700_000_000+secrets.randbelow(100_000_000)
    marker='rec-sync-'+uuid4().hex[:10]
    checks=[]; completed=False; es=BaseEsClient().client
    def check(name,passed):
        checks.append({'name':name,'passed':bool(passed)})
        print(name+': '+str(bool(passed)),flush=True)
        assert passed,name
    async def req(client,method,path,**kwargs):
        response=await client.request(method,path,**kwargs)
        body=response.json()
        assert response.status_code==200 and body.get('code')==200,(path,response.status_code,body.get('message'))
        return body['data']
    async def wait_until(predicate,timeout=30):
        deadline=asyncio.get_running_loop().time()+timeout
        while asyncio.get_running_loop().time()<deadline:
            if await predicate(): return True
            await asyncio.sleep(.3)
        return False
    await db.connect()
    try:
        for uid in [author,reader,admin]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,
                total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,'LocalRecommendQa2026!',:marker,NOW(),2,1,0,0,1,:role,0,0,0)''',
                {'uid':uid,'name':'推荐验证'+str(uid)[-10:],'email':f'{marker}-{uid}@sample.invalid','marker':marker,'role':2 if uid==admin else 1})
        await db.execute('''INSERT INTO category(category_id,category_name,parent_id,description,article_count,status,create_time,update_time)
            VALUES(:cid,:marker,0,:marker,0,1,NOW(),NOW())''',{'cid':category,'marker':marker})
        for aid,title in zip(articles,['Redis 教程','JavaScript 教程','RAG 指南','Redis 高阶','Redis 草稿','Redis 删除文章']):
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,category_id,
                view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,
                publish_time,create_time,update_time,deleted,required_level)
                VALUES(:aid,:uid,:title,:title,'<p>Disposable local verification</p>',1,:cid,:views,0,0,0,0,:status,0,0,1,
                    TIMESTAMPADD(DAY,-:days,NOW()),NOW(),NOW(),:deleted,:level)''',
                {'aid':aid,'uid':author,'title':title+' · '+marker,'cid':category,'views':5000 if aid==locked else 0,
                 'status':0 if aid==draft else 1,'days':30 if aid==redis else 0,'deleted':1 if aid==deleted else 0,'level':2 if aid==locked else 0})
        await db.execute('''INSERT INTO user_profile(user_id,tech_stack,interests,experience,preferences,create_time,update_time)
            VALUES(:uid,'["Redis"]','["redis"]','unknown','{}',NOW(),NOW())''',{'uid':reader})
        def client(uid=None):
            return httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30,
                headers={'Authorization':'Bearer '+local_token(uid)} if uid else {})
        async with client() as guest,client(reader) as user,client(author) as owner,client(admin) as manager:
            params={'page':1,'size':20,'categoryId':category}
            feed=await req(user,'GET','/article/recommend',params=params)
            check('explicit_topics_improve_cold_start_without_interaction',int(feed['records'][0]['articleId'])==redis)
            check('cold_start_reason_comes_from_explicit_profile',feed['records'][0]['recommendationReason']=='与你明确关注的领域相关')
            check('locked_popular_article_is_ranked_after_readable_articles',int(feed['records'][-1]['articleId'])==locked and not feed['records'][-1]['readableNow'])
            check('private_and_deleted_content_remains_excluded',feed['total']==4 and not {draft,deleted}&{int(r['articleId']) for r in feed['records']})
            overview=await req(user,'GET','/agent/memory')
            await req(user,'PUT','/agent/memory/profile',json={**overview['profile'],'version':overview['profile_version'],'topics':[]})
            feed=await req(user,'GET','/article/recommend',params=params)
            check('removing_explicit_topics_immediately_removes_explicit_boost',all(r['recommendationReason']!='与你明确关注的领域相关' for r in feed['records']))
            overview=await req(user,'GET','/agent/memory')
            await req(user,'PUT','/agent/memory/profile',json={**overview['profile'],'version':overview['profile_version'],'topics':['Java']})
            feed=await req(user,'GET','/article/recommend',params=params)
            check('java_does_not_match_javascript',next(r for r in feed['records'] if int(r['articleId'])==js)['recommendationReason']!='与你明确关注的领域相关')
            for endpoint in ['/article/recommend','/article/list']:
                for caller,name,total in [(guest,'guest',3),(user,'low_level',3),(owner,'author',4),(manager,'admin',4)]:
                    feed=await req(caller,'GET',endpoint,params={**params,'readableOnly':True})
                    check(name+'_readable_filter_'+endpoint.split('/')[-1],feed['total']==total and all(r['readableNow'] for r in feed['records']))
                first=await req(user,'GET',endpoint,params={**params,'readableOnly':True,'size':2})
                second=await req(user,'GET',endpoint,params={**params,'readableOnly':True,'size':2,'page':2})
                check('filtered_pagination_'+endpoint.split('/')[-1],first['total']==3 and first['pages']==2 and len(second['records'])==1 and not {r['articleId'] for r in first['records']}&{r['articleId'] for r in second['records']})
            await db.execute('INSERT INTO user_reading_progress(user_id,total_millis,earned_level) VALUES (:uid,0,2)',{'uid':reader})
            feed=await req(user,'GET','/article/recommend',params={**params,'readableOnly':True})
            check('earned_level_unlocks_feed_without_changing_author_permissions',feed['total']==4)
            await es.delete(index='article',id=str(redis),ignore=[404])
            reads=await asyncio.gather(*(req(user,'POST',f'/article/{redis}/view') for _ in range(20)))
            check('twenty_concurrent_duplicate_reads_count_once',sum(r['counted'] for r in reads)==1 and await db.fetch_val('SELECT view_count FROM article_info WHERE article_id=:aid',{'aid':redis})==1)
            async def attempted():
                return (await db.fetch_val('SELECT attempts FROM article_view_sync WHERE article_id=:aid',{'aid':redis}) or 0)>0
            check('missing_es_document_keeps_durable_retry',await wait_until(attempted))
            await es.index(index='article',id=str(redis),document={'articleId':redis,'userId':author,'title':'Redis QA','viewCount':0,'status':1},refresh=True)
            async def caught_up():
                remaining=await db.fetch_val('SELECT COUNT(*) FROM article_view_sync WHERE article_id=:aid',{'aid':redis})
                document=await es.get(index='article',id=str(redis))
                count=await db.fetch_val('SELECT view_count FROM article_info WHERE article_id=:aid',{'aid':redis})
                return not remaining and document['_source']['viewCount']==count
            check('retry_recovers_when_search_document_becomes_available',await wait_until(caught_up))
            await req(guest,'POST',f'/article/{redis}/view')
            await req(manager,'POST',f'/article/{redis}/view')
            check('coalesced_counter_converges_to_latest_mysql_value',await wait_until(caught_up) and await db.fetch_val('SELECT view_count FROM article_info WHERE article_id=:aid',{'aid':redis})==3)
            ignored=await req(owner,'POST',f'/article/{redis}/view')
            check('author_self_reads_do_not_increment_or_enqueue',not ignored['counted'] and ignored['viewCount']==3)
            if '--preview' in sys.argv:
                print(f'Preview account: {marker}-{reader}@sample.invalid / LocalRecommendQa2026!',flush=True)
                print(f'Preview category: {marker}',flush=True)
                await asyncio.to_thread(input,'Enter after UI verification to clean fixtures: ')
            completed=True
    finally:
        for aid in articles:
            if await db.fetch_val('SELECT user_id FROM article_info WHERE article_id=:aid',{'aid':aid})!=author: continue
            for table in ['article_view_sync','article_read_receipt','article_tag_relation']:
                await db.execute(f'DELETE FROM {table} WHERE article_id=:aid',{'aid':aid})
            await db.execute('DELETE FROM user_action WHERE article_id=:aid AND user_id IN (:r,:a,:m)',{'aid':aid,'r':reader,'a':author,'m':admin})
            await db.execute('DELETE FROM article_info WHERE article_id=:aid AND user_id=:uid',{'aid':aid,'uid':author})
            await es.delete(index='article',id=str(aid),ignore=[404])
        for uid in [author,reader,admin]:
            if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})!=1: continue
            for table in ['user_profile','user_reading_progress']:
                await db.execute(f'DELETE FROM {table} WHERE user_id=:uid',{'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})
        await db.execute('DELETE FROM category WHERE category_id=:cid AND category_name=:marker',{'cid':category,'marker':marker})
        await db.disconnect(); await es.close()
        output=ROOT/'logs/evaluation'/f'recommendation-access-sync-{datetime.now():%Y%m%d-%H%M%S}.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({'passed':completed,'checks':checks,'cleanup_complete':True,'scope':'isolated local Java HTTP + MySQL + Elasticsearch'},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Report: {output}',flush=True)

if __name__=='__main__': asyncio.run(main())
