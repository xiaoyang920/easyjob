"""Isolated real Java/MySQL checks. No LLM calls or changes to existing users/articles."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token
from app.services.filter_resolver import FilterResolver, FilterResolutionError
from app.services.query_rewrite import QueryFilters


async def main():
    if db.url.hostname not in {'localhost', '127.0.0.1', '::1'}: raise RuntimeError('Local fixtures only')
    ids = SnowflakeGenerator(worker_id=26)
    author, reader = ids.next_id(), ids.next_id()
    category, other_category, tag = ids.next_id(), ids.next_id(), ids.next_id()
    article_ids = [ids.next_id() for _ in range(6)]
    a, interest, old, private, deleted, other = article_ids
    marker = 'reading-' + uuid4().hex[:10]
    completed = False
    report = {'checks': [], 'scope': 'real local Java HTTP and MySQL; synthetic isolated fixtures; no model calls', 'cleanup_complete': False}
    output = ROOT / 'logs/evaluation' / f'recommendation-reading-{datetime.now():%Y%m%d-%H%M%S}.json'
    def check(name, passed, **details):
        item = {'name': name, 'passed': bool(passed), **details}
        report['checks'].append(item); print(json.dumps(item, ensure_ascii=False), flush=True)
        if not passed: raise AssertionError(name)
    async def req(client, method, path, **kwargs):
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 200: raise RuntimeError('Fixture API failed: ' + str(result.get('code')))
        return result['data']
    await db.connect()
    try:
        for uid in [author, reader]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
                sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,1,0,0,0)''',
                {'uid': uid, 'name': marker + ('作者' if uid == author else '读者'), 'email': f'{marker}-{uid}@sample.invalid', 'marker': marker})
        for cid in [category, other_category]:
            await db.execute('''INSERT INTO category(category_id,category_name,parent_id,description,article_count,status,create_time,update_time)
                VALUES(:id,:name,0,:name,0,1,NOW(),NOW())''', {'id': cid, 'name': f'{marker}-{cid}'})
        await db.execute('INSERT INTO article_tag(tag_id,tag_name,use_count,create_time) VALUES (:id,:name,0,NOW())', {'id': tag, 'name': marker})
        for aid, days, views, status, removed, cid in [(a,0,0,1,0,category),(interest,30,0,1,0,category),
                (old,365,100,1,0,category),(private,0,0,0,0,category),(deleted,0,0,1,1,category),(other,0,0,1,0,other_category)]:
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,category_id,
                view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,
                publish_time,create_time,update_time,deleted)
                VALUES(:aid,:uid,:title,:title,'<p>Isolated regression fixture</p>',1,:cid,:views,0,0,0,0,:status,0,0,1,
                TIMESTAMPADD(DAY,-:days,NOW()),NOW(),NOW(),:removed)''',
                {'aid': aid, 'uid': author, 'title': f'{marker}-{aid}', 'cid': cid, 'views': views, 'status': status, 'days': days, 'removed': removed})
        for aid in [interest, private]:
            await db.execute('INSERT INTO article_tag_relation(article_id,tag_id,create_time) VALUES (:aid,:tid,NOW())', {'aid': aid, 'tid': tag})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30) as guest, \
                httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30,headers={'Authorization':'Bearer '+local_token(reader)}) as user, \
                httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30,headers={'Authorization':'Bearer '+local_token(author)}) as owner:
            feed = await req(guest, 'GET', '/article/recommend', params={'page':1,'size':10,'categoryId':category})
            check('recommendation_is_paginated_and_respects_visibility', feed['total']==3 and {int(r['articleId']) for r in feed['records']}=={a,interest,old})
            check('fresh_zero_view_article_can_rank_above_year_old_popularity', int(feed['records'][0]['articleId'])==a)
            first = await req(guest,'GET','/article/recommend',params={'page':1,'size':1,'categoryId':category})
            second = await req(guest,'GET','/article/recommend',params={'page':2,'size':1,'categoryId':category})
            check('stable_pagination_has_distinct_records', first['records'][0]['articleId']!=second['records'][0]['articleId'] and first['pages']==3)
            by_tag = await req(guest,'GET','/article/recommend',params={'page':1,'tagIds':tag,'categoryId':category})
            check('tag_filter_does_not_expose_private_article', [int(r['articleId']) for r in by_tag['records']]==[interest])
            latest_tag = await req(guest,'GET','/article/list',params={'page':1,'tagIds':tag,'categoryId':category})
            check('tag_filter_also_applies_to_regular_feed', [int(r['articleId']) for r in latest_tag['records']]==[interest])
            category_feed = await req(guest,'GET','/article/recommend',params={'page':1,'categoryId':other_category})
            check('category_filter_is_applied', [int(r['articleId']) for r in category_feed['records']]==[other])
            check('legacy_recommend_list_is_bounded', len(await req(guest,'GET','/article/recommend',params={'limit':9999}))<=50)
            await req(guest,'GET',f'/article/detail/{a}')
            check('detail_get_does_not_count_as_reading', await db.fetch_val('SELECT view_count FROM article_info WHERE article_id=:id',{'id':a})==0)
            results = await asyncio.gather(*(req(user,'POST',f'/article/{a}/view') for _ in range(20)))
            check('twenty_concurrent_reads_increment_once', sum(r['counted'] for r in results)==1 and all(r['viewCount']==1 for r in results), requests=20)
            check('one_logged_in_history_row_with_correct_author', await db.fetch_val('''SELECT COUNT(*) FROM user_action WHERE
                user_id=:uid AND article_id=:aid AND article_user_id=:author AND action_type=7''',{'uid':reader,'aid':a,'author':author})==1)
            check('owner_read_does_not_inflate_count', (await req(owner,'POST',f'/article/{a}/view'))=={'counted':False,'viewCount':1})
            guest_results = await asyncio.gather(*(req(guest,'POST',f'/article/{a}/view') for _ in range(12)))
            check('anonymous_cookie_reads_are_deduplicated',sum(r['counted'] for r in guest_results)==1 and all(r['viewCount']==2 for r in guest_results),requests=12)
            check('same_reader_cannot_recount_with_another_request',not (await req(user,'POST',f'/article/{a}/view'))['counted'])
            # A new date is represented by aging this fixture's receipt, without changing server clocks.
            await db.execute('''UPDATE article_read_receipt SET read_day=DATE_SUB(read_day,INTERVAL 1 DAY)
                WHERE article_id=:aid AND reader_hash=:reader''',{'aid':a,'reader':__import__('hashlib').sha256(f'user:{reader}'.encode()).hexdigest()})
            check('next_day_can_count_same_reader_again',(await req(user,'POST',f'/article/{a}/view'))['viewCount']==3)
            check('detail_returns_current_database_count',(await req(guest,'GET',f'/article/detail/{a}'))['viewCount']==3)
            for aid in [private,deleted]:
                response=await guest.post(f'/article/{aid}/view')
                check('unavailable_article_cannot_receive_reads_'+str(aid),response.status_code==404 or response.json().get('code')==404)
                response=await guest.get(f'/article/detail/{aid}')
                check('unavailable_article_detail_is_not_exposed_'+str(aid),response.status_code==404 or response.json().get('code')==404)
            # Provide a fresh unread alternative. Demotion alone does not promise
            # a rank change when every alternative was read or has a weaker score.
            await db.execute('UPDATE article_info SET publish_time=TIMESTAMPADD(HOUR,-2,NOW()),view_count=0 WHERE article_id=:id AND user_id=:uid', {'id':old,'uid':author})
            await db.execute('''INSERT INTO user_action(user_id,article_id,article_user_id,comment_id,action_type,action_count,action_time)
                VALUES(:uid,:aid,:author,0,2,1,NOW())''',{'uid':reader,'aid':interest,'author':author})
            personalized = await req(user,'GET','/article/recommend',params={'page':1,'size':10,'categoryId':category})
            check('interest_updates_without_waiting_for_nightly_refresh',int(personalized['records'][0]['articleId'])==interest)
            check('recommendation_reason_matches_interest',personalized['records'][0]['recommendationReason']=='与你近期阅读和互动相关')
            await req(user,'POST',f'/article/{interest}/view')
            personalized = await req(user,'GET','/article/recommend',params={'page':1,'size':10,'categoryId':category})
            check('recent_read_article_is_demoted_without_permanent_exclusion',int(personalized['records'][0]['articleId'])!=interest and str(interest) in [r['articleId'] for r in personalized['records']])
        # An unknown nickname must not become a loose keyword search.
        try: await FilterResolver().resolve(QueryFilters(author_name=marker))
        except FilterResolutionError: check('unknown_author_scope_does_not_broaden',True)
        else: check('unknown_author_scope_does_not_broaden',False)
        for label, sql in [('expiry','SELECT run_id FROM agent_run WHERE status=\'running\' AND deadline<=UTC_TIMESTAMP(6) ORDER BY deadline LIMIT 100'),
            ('recent_runs','SELECT run_id FROM agent_run WHERE created_at>=TIMESTAMPADD(HOUR,-24,NOW(6)) ORDER BY created_at DESC LIMIT 2001')]:
            rows=await db.fetch_all('EXPLAIN '+sql)
            report.setdefault('explain',{})[label]=[{k:r._mapping[k] for k in ('table','type','possible_keys','key','rows','Extra')} for r in rows]
        completed = True
    finally:
        # Generated IDs and owner predicates constrain all fixture cleanup.
        for aid in article_ids:
            owner_id=await db.fetch_val('SELECT user_id FROM article_info WHERE article_id=:id',{'id':aid})
            if owner_id is None: continue
            if owner_id!=author: raise RuntimeError('Fixture ownership changed; cleanup stopped')
            await db.execute('DELETE FROM article_read_receipt WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM article_view_sync WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM user_action WHERE article_id=:id AND user_id IN (:u,:a)',{'id':aid,'u':reader,'a':author})
            await db.execute('DELETE FROM article_tag_relation WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM article_info WHERE article_id=:id AND user_id=:u',{'id':aid,'u':author})
        await db.execute('DELETE FROM article_tag WHERE tag_id=:id AND tag_name=:name',{'id':tag,'name':marker})
        for cid in [category,other_category]:
            await db.execute('DELETE FROM category WHERE category_id=:id AND category_name=:name',{'id':cid,'name':f'{marker}-{cid}'})
        for uid in [reader,author]:
            await db.execute('DELETE FROM user_info WHERE user_id=:u AND person_introduction=:marker',{'u':uid,'marker':marker})
        report['cleanup_complete']=True
        report['passed']=completed and all(c['passed'] for c in report['checks'])
        output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        await db.disconnect()
        print('Report: '+str(output))


if __name__=='__main__': asyncio.run(main())
