"""Real local HTTP/MySQL permission and concurrency checks with disposable owners.

Elapsed intervals are simulated by aging fixture session timestamps, never production clocks.
"""
import asyncio
from datetime import datetime
import json
import hashlib
from pathlib import Path
import sys
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient
from app.config import settings
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token
from app.services.article_context import ArticleContextService
from app.graph.nodes.search_worker import _verify_candidates_from_mysql
from app.services.evidence_verifier import verify_public_evidence
from app.services.retrieval_service import ARTICLE_CHUNK_VERSION
from fastapi import HTTPException


async def main():
    if db.url.hostname not in {'127.0.0.1','localhost','::1'}: raise RuntimeError('Local fixtures only')
    ids=SnowflakeGenerator(worker_id=24)
    author,reader,admin,other,category=[ids.next_id() for _ in range(5)]
    public,locked,own,draft,deleted=[ids.next_id() for _ in range(5)]
    users=[author,reader,admin,other]; articles=[public,locked,own,draft,deleted]
    marker='rlevel-'+uuid4().hex[:10]
    secret='PRIVATE-BODY-'+marker
    report={'scope':'real Java HTTP/MySQL; isolated authored fixtures; timestamp aging simulates elapsed time; no LLM calls','checks':[],'cleanup_complete':False}
    output=ROOT/'logs/evaluation'/f'reading-level-{datetime.now():%Y%m%d-%H%M%S}.json'
    def check(name,passed):
        item={'name':name,'passed':bool(passed)}; report['checks'].append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
        if not passed: raise AssertionError(name)
    async def req(client,method,path,**kwargs):
        res=await client.request(method,path,**kwargs); data=res.json()
        if res.status_code!=200 or data.get('code')!=200: raise RuntimeError(f'{path}: {res.status_code}, {data.get("code")}, {data.get("message")}')
        return data['data']
    async def deny(client,method,path,code,**kwargs):
        res=await client.request(method,path,**kwargs)
        return res.status_code==code or res.json().get('code')==code
    async def age(sid,seconds):
        await db.execute('UPDATE reading_session SET last_heartbeat=TIMESTAMPADD(SECOND,-:sec,last_heartbeat) WHERE session_id=:sid AND user_id=:uid',{'sid':sid,'sec':seconds,'uid':reader})
    async def beat(client,sid,seq,active=True):
        return await req(client,'POST','/reading/heartbeat',json={'sessionId':sid,'sequence':seq,'active':active})
    await db.connect()
    try:
        for uid in users:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,
                total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,'NotALoginCredential!',:marker,NOW(),2,1,0,0,1,:role,0,0,0)''',
                {'uid':uid,'name':'等级'+str(uid)[-8:],'email':f'{marker}-{uid}@sample.invalid','marker':marker,'role':2 if uid==admin else 1})
        await db.execute('''INSERT INTO category(category_id,category_name,parent_id,description,article_count,status,create_time,update_time)
            VALUES(:id,:marker,0,:marker,0,1,NOW(),NOW())''',{'id':category,'marker':marker})
        for aid in articles:
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,category_id,view_count,like_count,
                collect_count,comment_count,share_count,status,is_top,is_essence,is_original,publish_time,create_time,update_time,deleted,required_level)
                VALUES(:aid,:uid,:title,'Public description',:body,1,:cat,0,0,0,0,0,:status,0,0,1,NOW(),NOW(),NOW(),:deleted,:level)''',
                {'aid':aid,'uid':reader if aid==own else author,'title':marker+str(aid),'body':f'<p>{secret}</p>',
                 'cat':category,'status':0 if aid==draft else 1,'deleted':1 if aid==deleted else 0,'level':1 if aid==locked else 0})
        def client(uid=None):
            return httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=25,
                headers={'Authorization':'Bearer '+local_token(uid)} if uid else {})
        async with client() as guest,client(reader) as user,client(author) as owner,client(admin) as manager,client(other) as outsider:
            detail=await req(guest,'GET',f'/article/detail/{locked}')
            check('anonymous_detail_redacts_full_body',detail['content'] is None and not detail['canReadFull'] and secret not in json.dumps(detail))
            detail=await req(user,'GET',f'/article/detail/{locked}')
            check('low_level_detail_redacts_cached_full_body',detail['content'] is None and detail['readerLevel']==0)
            check('owner_can_read_own_restricted_body',secret in (await req(owner,'GET',f'/article/detail/{locked}'))['content'])
            check('administrator_can_read_for_management',(await req(manager,'GET',f'/article/detail/{locked}'))['viewerAdmin'])
            check('nonadmin_cannot_change_gate',await deny(user,'PUT',f'/article/{locked}/reading-level',403,json={'level':0}))
            check('invalid_level_is_rejected',await deny(manager,'PUT',f'/article/{locked}/reading-level',400,json={'level':99}))
            check('guest_cannot_create_reading_session',await deny(guest,'POST','/reading/sessions',401,json={'articleId':public,'active':True}))
            check('restricted_article_cannot_generate_time',await deny(user,'POST','/reading/sessions',403,json={'articleId':locked,'active':True}))
            check('own_article_cannot_generate_time',await deny(user,'POST','/reading/sessions',409,json={'articleId':own,'active':True}))
            for aid in [draft,deleted]:
                check('unavailable_article_cannot_generate_time_'+str(aid),await deny(user,'POST','/reading/sessions',404,json={'articleId':aid,'active':True}))
            session=await req(user,'POST','/reading/sessions',json={'articleId':public,'active':True}); sid=session['sessionId']
            check('new_user_starts_at_zero',session['totalSeconds']==0 and session['level']==0)
            await age(sid,15)
            results=await asyncio.gather(*(beat(user,sid,1) for _ in range(10)))
            total=(await req(user,'GET','/reading/me'))['totalSeconds']
            check('ten_concurrent_identical_heartbeats_credit_once',15<=total<=20 and sum(r['creditedSeconds']>0 for r in results)==1)
            await age(sid,15)
            check('duplicate_sequence_does_not_credit_again',(await beat(user,sid,1))['totalSeconds']==total)
            paused=await beat(user,sid,2,False); await age(sid,15)
            check('paused_interval_is_not_credited',(await beat(user,sid,3,True))['totalSeconds']==paused['totalSeconds'])
            await age(sid,46)
            check('disconnected_interval_is_discarded',(await beat(user,sid,4))['creditedSeconds']==0)
            await age(sid,40)
            check('single_interval_is_capped_at_thirty_seconds',(await beat(user,sid,5))['creditedSeconds']==30)
            check('other_user_cannot_reuse_session',await deny(outsider,'POST','/reading/heartbeat',409,json={'sessionId':sid,'sequence':6,'active':True}))
            second=await req(user,'POST','/reading/sessions',json={'articleId':public,'active':True})
            check('opening_second_tab_revokes_first_counter',await deny(user,'POST','/reading/heartbeat',409,json={'sessionId':sid,'sequence':6,'active':True}))
            # Only this isolated fixture's total is seeded near a genuine threshold.
            await db.execute('UPDATE user_reading_progress SET total_millis=3590000 WHERE user_id=:uid',{'uid':reader})
            await age(second['sessionId'],15)
            promoted=await beat(user,second['sessionId'],1)
            check('threshold_crossing_persists_level_one',promoted['level']==1 and promoted['totalSeconds']>=3600)
            check('new_level_unlocks_full_body',secret in (await req(user,'GET',f'/article/detail/{locked}'))['content'])
            await req(manager,'PUT',f'/article/{locked}/reading-level',json={'level':2})
            detail=await req(user,'GET',f'/article/detail/{locked}')
            check('administrator_gate_change_applies_despite_cached_detail',detail['requiredLevel']==2 and detail['content'] is None)
            check('locked_view_endpoint_is_also_denied',await deny(user,'POST',f'/article/{locked}/view',403))
            check('home_list_exposes_gate_without_body',next(a for a in (await req(guest,'GET','/article/list',params={'categoryId':category}))['records'] if int(a['articleId'])==locked)['requiredLevel']==2)
            space=await req(guest,'GET',f'/user/space/{reader}')
            check('personal_space_reports_current_progress',space['readingProgress']['level']==1 and space['readingProgress']['totalSeconds']==promoted['totalSeconds'])
            # Mimic a rule becoming harder using an already earned fixture level, without editing global rules.
            await db.execute('UPDATE user_reading_progress SET earned_level=4 WHERE user_id=:uid',{'uid':reader})
            check('earned_level_never_downgrades',(await req(user,'GET','/reading/me'))['level']==4)
        try: await ArticleContextService().load(locked)
        except HTTPException as exc: check('ai_source_article_is_blocked_without_level_support',exc.status_code==404)
        else: check('ai_source_article_is_blocked_without_level_support',False)
        fingerprint=hashlib.sha256(f'<p>{secret}</p>'.encode()).hexdigest()
        async def candidate(aid):
            row=await db.fetch_one('SELECT title,user_id,category_id,publish_time FROM article_info WHERE article_id=:aid',{'aid':aid})
            return {**dict(row._mapping),'article_id':str(aid),'content':secret,'chunk_index':0,
                    'chunker_version':ARTICLE_CHUNK_VERSION,'source_hash':fingerprint,
                    'chunk_id':f'{aid}_{ARTICLE_CHUNK_VERSION}_{fingerprint}_0',
                    'publish_time':row._mapping['publish_time'].isoformat(),'tags':[]}
        public_candidate=await candidate(public)
        restricted_candidate=await candidate(locked)
        check('valid_public_ai_candidate_is_retained',len(await _verify_candidates_from_mysql([public_candidate]))==1)
        check('valid_restricted_ai_candidate_is_filtered_before_reranking',await _verify_candidates_from_mysql([restricted_candidate])==[])
        try:
            await verify_public_evidence([{'articleId':str(locked),'sourceHash':hashlib.sha256(f'<p>{secret}</p>'.encode()).hexdigest()}])
        except ValueError: check('old_ai_evidence_is_rechecked',True)
        else: check('old_ai_evidence_is_rechecked',False)
        if '--preview' in sys.argv:
            print(f'Preview: http://127.0.0.1:3000/article/{locked}',flush=True)
            print(f'Profile: http://127.0.0.1:3000/user-space/{reader}',flush=True)
            await asyncio.to_thread(input,'Press Enter after browser QA to clean up fixtures. ')
    finally:
        for uid in users:
            if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})!=1: continue
            async with db.transaction():
                for table in ['reading_session','user_reading_daily','user_reading_progress','user_action']:
                    await db.execute(f'DELETE FROM {table} WHERE user_id=:uid',{'uid':uid})
                for aid in articles:
                    await db.execute('DELETE FROM article_index_outbox WHERE article_id=:aid',{'aid':aid})
                    await db.execute('DELETE FROM article_read_receipt WHERE article_id=:aid',{'aid':aid})
                await db.execute('DELETE FROM article_info WHERE user_id=:uid AND category_id=:cat',{'uid':uid,'cat':category})
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND person_introduction=:marker',{'uid':uid,'marker':marker})
        await db.execute('DELETE FROM category WHERE category_id=:cat AND category_name=:marker',{'cat':category,'marker':marker})
        # The administrator policy check publishes a real asynchronous index update.
        # Remove only these generated fixture IDs from the local search indexes as well.
        if settings.ES_HOST not in {'127.0.0.1','localhost','::1'}:
            raise RuntimeError('Fixture index cleanup requires local Elasticsearch')
        es=BaseEsClient().client
        try:
            await es.delete_by_query(index='article',query={'ids':{'values':[str(aid) for aid in articles]}},refresh=True,conflicts='proceed')
            await es.delete_by_query(index='article_vectors',query={'terms':{'article_id':[str(aid) for aid in articles]}},refresh=True,conflicts='proceed')
        finally:
            await es.close()
        await db.disconnect()
        report['cleanup_complete']=True
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(output),flush=True)


if __name__=='__main__': asyncio.run(main())
