"""Local HTTP/MySQL/ES regression using isolated fixtures, without LLM/embedding calls."""
import asyncio,json,sys,hashlib
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient
from app.config import settings
from app.migrate import apply_maintenance_migration
from app.services.index_reconciliation import IndexReconciliation
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token

async def main():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'} and settings.ES_HOST in {'localhost','127.0.0.1','::1'}
    ids=SnowflakeGenerator(worker_id=27);admin,author,article,orphan=[ids.next_id() for _ in range(4)]
    marker='maintenance-'+uuid4().hex[:10];password='LocalOpsQa2026!';email=marker+'@sample.invalid'
    jid=str(uuid4());mid=hashlib.sha256(marker.encode()).hexdigest()
    client=BaseEsClient().client
    report={'checks':[],'scope':'isolated local HTTP/MySQL/ES; no model or embedding calls','cleanup_complete':False,'fixture_ids':{'admin':str(admin),'author':str(author),'article':str(article),'orphan':str(orphan),'job':jid,'memory_job':mid}}
    output=ROOT/'logs/evaluation'/f'maintenance-{datetime.now():%Y%m%d-%H%M%S}.json'
    def check(name,passed):
        item={'name':name,'passed':bool(passed)};report['checks'].append(item);print(json.dumps(item),flush=True);assert passed,name
    async def call(http,method,path,expected=200,**kwargs):
        response=await http.request(method,path,**kwargs);body=response.json();code=response.status_code if response.status_code!=200 else body.get('code')
        assert code==expected,(path,code,expected);return body.get('data')
    await db.connect()
    try:
        await apply_maintenance_migration(db);await apply_maintenance_migration(db)
        check('migration_replay_preserves_cursor_rows',await db.fetch_val('SELECT COUNT(*) FROM maintenance_cursor')==5)
        for uid in [admin,author]:
            await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,:password,NOW(),2,1,0,0,1,:role,0,0,0)""",{'uid':uid,'name':'Ops'+str(uid)[-8:],'email':email if uid==admin else marker+'-author@sample.invalid','password':password,'role':2 if uid==admin else 1})
        await db.execute("""INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,publish_time,create_time,update_time,deleted,required_level)
            VALUES(:id,:uid,:title,'summary','<p>isolated fixture</p>',1,4,0,0,0,0,1,0,0,1,NOW(),NOW(),NOW(),0,1)""",{'id':article,'uid':author,'title':marker})
        await db.execute("""INSERT INTO article_index_outbox(job_id,article_id,action,routing_key,status,attempts,last_error,available_at,created_at,updated_at)
            VALUES(:job,:id,'UPDATE','article.update','dead',8,'secret prompt must stay private','2050-01-01',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",{'job':jid,'id':article})
        await db.execute("""INSERT INTO agent_background_job(job_id,kind,user_id,payload,status,attempts,available_at,created_at,updated_at)
            VALUES(:id,'memory_extract',:uid,:payload,'dead',8,'2050-01-01',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",{'id':mid,'uid':author,'payload':json.dumps({'text':'secret memory body'})})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=15,headers={'Authorization':'Bearer '+local_token(admin)}) as manager,httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=15,headers={'Authorization':'Bearer '+local_token(author)}) as ordinary:
            for path in ['/admin/operations','/admin/operations/jobs','/admin/operations/runs']:await call(ordinary,'GET',path,403)
            await call(ordinary,'POST',f'/admin/operations/jobs/article/{jid}/retry',403)
            await call(ordinary,'POST','/admin/operations/reconcile',403,json={'kind':'article'})
            check('all_operational_routes_require_admin',True)
            summary=await call(manager,'GET','/admin/operations');check('summary_has_five_reconciliation_sweeps',len(summary['reconciliation'])==5)
            jobs=await call(manager,'GET','/admin/operations/jobs',params={'queue':'article','state':'dead','size':100})
            own=next(r for r in jobs['records'] if r['jobId']==jid)
            check('error_redacted_and_payload_not_exposed',own['error']=='task_failed' and 'secret' not in json.dumps(jobs) and all('payload' not in r and 'lease_token' not in r for r in jobs['records']))
            await call(manager,'GET','/admin/operations/jobs',400,params={'queue':'article;DROP TABLE user_info'})
            await call(manager,'GET','/admin/operations/runs',400,params={'state':'invalid'})
            await call(manager,'GET','/admin/operations/jobs',400,params={'size':101})
            check('sql_identifiers_and_bounds_reject_untrusted_input',True)
            runs=await call(manager,'GET','/admin/operations/runs');check('runs_expose_metadata_only',all(not {'result','error','metrics','execution_token','query'} & set(r) for r in runs['records']))
            await call(manager,'POST',f'/admin/operations/jobs/memory/{mid}/retry',409)
            check('retired_memory_extraction_cannot_be_revived',await db.fetch_val('SELECT status FROM agent_background_job WHERE job_id=:id',{'id':mid})=='dead')
            await call(manager,'POST',f'/admin/operations/jobs/article/{jid}/retry')
            # restricted article -> fulltext-only update; no embedding request.
            for _ in range(40):
                state=await db.fetch_val('SELECT status FROM article_index_outbox WHERE job_id=:id',{'id':jid})
                if state=='completed':break
                await asyncio.sleep(.5)
            check('dead_task_retry_converges_on_latest_article',state=='completed')
            await call(manager,'POST',f'/admin/operations/jobs/article/{jid}/retry',409)
            check('retry_is_audited_once',await db.fetch_val("SELECT COUNT(*) FROM admin_operation_log WHERE admin_user_id=:uid AND action='task_retry' AND target_id=:aid",{'uid':admin,'aid':article})==1)
            engine=IndexReconciliation(db)
            raw=await db.fetch_one('SELECT * FROM article_info WHERE article_id=:id',{'id':article});snapshot=dict(raw._mapping)
            async with db.transaction():
                check('views_repair_uses_durable_coalesced_queue',await engine.article_repair(snapshot,'view_count'))
                check('view_target_never_decrements',await db.fetch_val('SELECT target_count FROM article_view_sync WHERE article_id=:id',{'id':article})==4)
            await client.index(index='article',id=str(orphan),document={'articleId':orphan,'title':marker,'status':1},refresh=True)
            await client.index(index='article_vectors',id=marker+'-chunk',document={'article_id':str(orphan),'chunk_content':'isolated orphan','chunk_index':0},refresh=True)
            check('orphan_repair_is_enqueued',await engine.article_repair(None,'orphan',orphan))
            for _ in range(40):
                alive=await client.exists(index='article',id=str(orphan))
                if not alive:break
                await asyncio.sleep(.5)
            await client.indices.refresh(index='article_vectors')
            check('orphan_document_and_chunks_removed',not alive and (await client.count(index='article_vectors',query={'term':{'article_id':str(orphan)}}))['count']==0)
            if '--preview' in sys.argv:
                print(json.dumps({'preview':{'email':email,'password':password,'url':'http://127.0.0.1:3000/admin?section=operations'}}),flush=True)
                await asyncio.to_thread(input,'Press Enter to clean fixtures: ')
    finally:
        try:
            # SQL cleanup is independent of ES availability, so service failures cannot leak accounts.
            for aid in [article,orphan]:
                await db.execute('DELETE FROM article_index_outbox WHERE article_id=:id',{'id':aid})
                await db.execute('DELETE FROM article_view_sync WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM article_info WHERE article_id=:id',{'id':article})
            await db.execute('DELETE FROM agent_background_job WHERE job_id=:id',{'id':mid})
            await db.execute('DELETE FROM admin_operation_log WHERE admin_user_id=:id',{'id':admin})
            for uid in [admin,author]:
                for table in ['reading_session','user_reading_daily','user_reading_progress']:
                    await db.execute(f'DELETE FROM {table} WHERE user_id=:id',{'id':uid})
                await db.execute('DELETE FROM user_info WHERE user_id=:id',{'id':uid})
            report['cleanup_complete']=True
            for aid in [article,orphan]:
                try:
                    await client.options(ignore_status=[404]).delete(index='article',id=str(aid),refresh=True)
                    await client.options(ignore_status=[404]).delete_by_query(index='article_vectors',query={'term':{'article_id':str(aid)}},refresh=True,conflicts='proceed')
                except Exception as error:
                    report['cleanup_complete']=False;report['cleanup_error']=type(error).__name__
        finally:
            output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(str(output),flush=True);await client.close();await db.disconnect()

if __name__=='__main__':asyncio.run(main())
