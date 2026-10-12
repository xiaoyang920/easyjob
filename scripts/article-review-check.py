"""Local real HTTP/MySQL revision lifecycle checks using isolated disposable fixtures."""
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
    ids=SnowflakeGenerator(worker_id=26);admin,author,foreign,cat=[ids.next_id() for _ in range(4)]
    marker='review-'+uuid4().hex[:10];password='LocalReviewQa2026!';article_ids=[]
    report={'scope':'real local HTTP/MySQL; isolated fixtures; no LLM calls','checks':[],'cleanup_complete':False}
    output=ROOT/'logs/evaluation'/f'article-review-{datetime.now():%Y%m%d-%H%M%S}.json'
    def check(name,value):report['checks'].append({'name':name,'passed':bool(value)});print(name+': '+str(bool(value)),flush=True);assert value,name
    def client(uid=None):return httpx.AsyncClient(base_url='http://127.0.0.1:8080/api',trust_env=False,timeout=30,headers={'Authorization':'Bearer '+local_token(uid)} if uid else {})
    async def call(client,method,path,code=200,**kwargs):
        body=kwargs.get('json')
        if method in ('PUT','POST') and isinstance(body,dict) and 'expectedRevisionId' in body and 'expectedLockVersion' not in body and path!='/article/create' and code!=404:
            baseline=(await client.get(f"/article/{path.split('/')[2]}/edit")).json()
            body['expectedLockVersion']=(baseline.get('data') or {}).get('lockVersion',0)
        response=await client.request(method,path,**kwargs);body=response.json();actual=body.get('code') if response.status_code==200 else response.status_code
        if actual!=code:raise AssertionError(f'{path}: expected {code}, got {actual}, {body.get("message")}')
        return body.get('data')
    async def scalar(sql,**params):return await db.fetch_val(sql,params)
    def payload(title,content,status=1,head='0',tags=None):return {'title':marker+' · '+title,'content':'<p>'+content+'</p>','summary':'审核版本样例','categoryId':str(cat),'contentType':1,'status':status,'expectedRevisionId':head,'isOriginal':1,'tagNames':tags or []}
    await db.connect()
    try:
        for uid in [admin,author,foreign]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,:password,:marker,NOW(),2,1,0,0,1,:role,0,0,0)''',{'uid':uid,'name':('审核管理员' if uid==admin else '版本作者')+str(uid)[-6:],'email':marker+('-admin' if uid==admin else '-author' if uid==author else '-foreign')+'@sample.invalid','password':password,'marker':marker,'role':2 if uid==admin else 1})
        await db.execute('INSERT INTO category(category_id,category_name,parent_id,description,article_count,status,create_time,update_time) VALUES(:id,:marker,0,:marker,0,1,NOW(),NOW())',{'id':cat,'marker':marker})
        async with client(admin) as manager,client(author) as owner,client(foreign) as outsider,client() as guest:
            created=await call(owner,'POST','/article/create',json=payload('初次提交','公开旧版内容'))
            aid=created['articleId'];article_ids.append(aid)
            await db.execute('UPDATE article_revision SET required_level=1 WHERE article_id=:id',{'id':aid})
            check('new_submission_has_no_info_row',await scalar('SELECT COUNT(*) FROM article_info WHERE article_id=:id',id=aid)==0)
            edit=await call(owner,'GET',f'/article/{aid}/edit');head=edit['revisionId']
            check('first_submission_stays_private',edit['status']==0 and edit['revisionState']==1 and await scalar('SELECT article_count FROM user_info WHERE user_id=:id',id=author)==0)
            await call(guest,'GET',f'/article/detail/{aid}',404);check('pending_body_is_not_public',True)
            await call(outsider,'GET',f'/article/{aid}/edit',404);await call(outsider,'GET',f'/article/{aid}/revisions',404)
            await call(owner,'GET',f'/admin/reviews/{head}',403);await call(owner,'POST',f'/admin/reviews/{head}',403,json={'decision':'approve'})
            check('only_owner_and_admin_can_read_private_versions',True)
            await call(owner,'PUT',f'/article/{aid}',409,json=payload('违规改动','未审核内容',head=head));check('pending_snapshot_cannot_be_mutated',True)
            before=await scalar('SELECT COUNT(*) FROM article_index_outbox WHERE article_id=:id',id=aid);check('submissions_do_not_publish_index_events',before==0)
            await call(manager,'POST',f'/admin/reviews/{head}',400,json={'decision':'reject','reason':' '});check('rejection_requires_reason',True)
            check('invalid_review_does_not_notify',await scalar('SELECT COUNT(*) FROM notification WHERE user_id=:id',id=author)==0)
            await call(manager,'POST',f'/admin/reviews/{head}',json={'decision':'reject','reason':'请补充完整示例'})
            rejected=(await call(owner,'GET','/notification/list',params={'type':6}))['records']
            check('rejection_notifies_author_with_reviewed_revision',len(rejected)==1 and rejected[0]['type']==7 and rejected[0]['targetId']==head and rejected[0]['articleId']==aid and rejected[0]['targetPreview']=='请补充完整示例' and rejected[0]['isRead']==0)
            rejected_notification=rejected[0]['notificationId']
            await call(outsider,'POST',f'/notification/{rejected_notification}/read')
            check('foreign_user_cannot_mark_review_notice_read',await scalar('SELECT is_read FROM notification WHERE notification_id=:id',id=rejected_notification)==0)
            check('foreign_user_cannot_list_review_notices',(await call(outsider,'GET','/notification/list',params={'type':6}))['total']==0)
            edit=await call(owner,'GET',f'/article/{aid}/edit');check('author_sees_rejection_reason',edit['revisionState']==3 and edit['reviewReason']=='请补充完整示例')
            pending=await call(owner,'POST',f'/article/{aid}/publish',json={'expectedRevisionId':head});approved_id=pending['revisionId']
            check('resubmit_creates_distinct_revision',approved_id!=head)
            repeat=await call(owner,'POST',f'/article/{aid}/publish',json={'expectedRevisionId':approved_id});check('duplicate_submit_is_idempotent',repeat['revisionId']==approved_id)
            await call(manager,'POST',f'/admin/reviews/{head}',409,json={'decision':'approve'});check('old_review_cannot_approve_new_content',True)
            async with owner.stream('GET','/notification/stream') as stream:
                assert stream.status_code==200
                results=await asyncio.gather(*(manager.post(f'/admin/reviews/{approved_id}',json={'decision':'approve'}) for _ in range(10)))
                async def approval_push():
                    async for line in stream.aiter_lines():
                        if line.startswith('data:'):
                            try: msg=json.loads(line[5:])
                            except ValueError: continue
                            if isinstance(msg,dict) and msg.get('type')==6:return msg
                pushed=await asyncio.wait_for(approval_push(),15)
                check('committed_approval_reaches_online_author_with_exact_string_ids',isinstance(pushed['notificationId'],str) and pushed['articleId']==aid and pushed['targetId']==approved_id and pushed['isRead']==0 and bool(pushed['createTime']))
            codes=[r.json()['code'] for r in results];check('ten_concurrent_approvals_commit_once',codes.count(200)==1 and codes.count(409)==9)
            check('ten_concurrent_approvals_notify_once',await scalar('SELECT COUNT(*) FROM notification WHERE user_id=:uid AND target_id=:rid AND type=6',uid=author,rid=approved_id)==1)
            check('first_approval_counts_once',await scalar('SELECT article_count FROM user_info WHERE user_id=:id',id=author)==1)
            public=await call(owner,'GET',f'/article/detail/{aid}');check('approved_version_becomes_public',public['content']=='<p>公开旧版内容</p>')
            publish_time=await scalar('SELECT publish_time FROM article_info WHERE article_id=:id',id=aid)
            edit=await call(owner,'GET',f'/article/{aid}/edit')
            await call(owner,'PUT',f'/article/{aid}',400,json=payload('无基准','错误',head=None));check('editor_requires_version_baseline',True)
            modified=await call(owner,'PUT',f'/article/{aid}',json=payload('修改草稿','新版暂未公开',0,edit['revisionId']));draft_id=modified['revisionId']
            check('published_article_edit_preserves_public_content',(await call(owner,'GET',f'/article/detail/{aid}'))['content']==public['content'])
            await call(owner,'PUT',f'/article/{aid}',409,json=payload('过期编辑','错误',0,edit['revisionId']));check('stale_editor_cannot_overwrite',True)
            pending=await call(owner,'POST',f'/article/{aid}/publish',json={'expectedRevisionId':draft_id});withdrawn=pending['revisionId']
            await call(owner,'POST',f'/article/{aid}/revisions/{withdrawn}/withdraw')
            await call(manager,'POST',f'/admin/reviews/{withdrawn}',409,json={'decision':'approve'});check('withdrawn_version_cannot_be_approved',True)
            modified=await call(owner,'PUT',f'/article/{aid}',json=payload('修改提交','新版已补全示例',1,withdrawn));new_id=modified['revisionId']
            long_reason='仍需说明边界，补充示例。'*80
            await call(manager,'POST',f'/admin/reviews/{new_id}',json={'decision':'reject','reason':long_reason})
            long_notice=(await call(owner,'GET','/notification/list',params={'type':7}))['records'][0]
            check('notification_keeps_reviewed_title_and_safe_reason_preview',long_notice['articleTitle']==marker+' · 修改提交' and long_notice['targetId']==new_id and len(long_notice['targetPreview'])<=200 and long_notice['targetPreview'].endswith('…'))
            check('rejection_link_can_read_complete_immutable_reason',(await call(owner,'GET',f'/article/{aid}/revisions/{new_id}'))['reason']==long_reason)
            check('rejecting_edit_keeps_old_version_visible',(await call(owner,'GET',f'/article/detail/{aid}'))['content']==public['content'])
            pending=await call(owner,'POST',f'/article/{aid}/publish',json={'expectedRevisionId':new_id});new_id=pending['revisionId']
            await call(manager,'POST',f'/admin/reviews/{new_id}',json={'decision':'approve','reason':'通过'})
            check('approved_edit_replaces_public_content',(await call(owner,'GET',f'/article/detail/{aid}'))['content']=='<p>新版已补全示例</p>')
            reviewed=await call(manager,'GET',f'/admin/reviews/{new_id}');check('historical_review_preserves_original_public_baseline',reviewed['publicPayload']['content']==public['content'])
            check('edit_approval_preserves_count_and_publish_time',await scalar('SELECT article_count FROM user_info WHERE user_id=:id',id=author)==1 and await scalar('SELECT publish_time FROM article_info WHERE article_id=:id',id=aid)==publish_time)
            history=await call(owner,'GET',f'/article/{aid}/revisions');check('history_retains_approved_rejected_and_withdrawn',all(s in {r['state'] for r in history} for s in [2,3,4]))
            restored=await call(owner,'POST',f'/article/{aid}/revisions/{approved_id}/restore',json={'expectedRevisionId':new_id});restored_id=restored['revisionId']
            check('restore_creates_draft_without_rolling_back_public',(await call(owner,'GET',f'/article/{aid}/edit'))['content']==public['content'] and (await call(owner,'GET',f'/article/detail/{aid}'))['content']=='<p>新版已补全示例</p>')
            await call(owner,'POST',f'/article/{aid}/revisions/{restored_id}/discard');check('discard_restores_editor_head_only',(await call(owner,'GET',f'/article/{aid}/edit'))['revisionId']==new_id)
            await call(outsider,'POST',f'/article/{aid}/revisions/{new_id}/restore',404,json={'expectedRevisionId':new_id});check('foreign_author_cannot_restore_snapshot',True)
            logs=await db.fetch_all('SELECT action FROM article_review_log WHERE article_id=:id',{'id':aid});check('audit_has_submit_reject_withdraw_approve_discard',{'submit','reject','withdraw','approve','discard'}.issubset({r['action'] for r in logs}))
            check('only_approved_versions_update_index',await scalar('SELECT COUNT(*) FROM article_index_outbox WHERE article_id=:id',id=aid)==2)
            await call(manager,'PUT',f'/admin/articles/{aid}/visibility',json={'expectedStatus':1,'status':2})
            await call(owner,'PUT',f'/article/{aid}',409,json=payload('下架绕过','违规',1,new_id));check('moderated_article_cannot_bypass_takedown',True)
            await call(manager,'PUT',f'/admin/articles/{aid}/visibility',json={'expectedStatus':2,'status':1})
            # Legacy published rows must be snapshotted without changing public content.
            legacy=str(ids.next_id());article_ids.append(legacy)
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,category_id,view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,publish_time,create_time,update_time,deleted,required_level)
                VALUES(:id,:uid,:title,'旧版样例','<p>迁移前已公开正文</p>',1,:cat,12,3,2,0,0,1,0,0,1,NOW(),NOW(),NOW(),0,1)''',{'id':legacy,'uid':author,'title':marker+' · 旧文章','cat':cat})
            await db.execute('UPDATE user_info SET article_count=article_count+1 WHERE user_id=:id',{'id':author})
            migrated=await call(owner,'PUT',f'/article/{legacy}',json=payload('旧文章修改','旧文章修改待审',1,'0'))
            legacy_history=await call(owner,'GET',f'/article/{legacy}/revisions')
            check('legacy_publication_gets_approved_baseline_snapshot',len(legacy_history)==2 and legacy_history[1]['state']==2 and (await call(owner,'GET',f'/article/detail/{legacy}'))['content']=='<p>迁移前已公开正文</p>')
            await call(manager,'POST',f'/admin/reviews/{migrated["revisionId"]}',json={'decision':'approve'})
            check('legacy_revision_approval_preserves_engagement',(await call(owner,'GET',f'/article/detail/{legacy}'))['viewCount']==12 and await scalar('SELECT like_count FROM article_info WHERE article_id=:id',id=legacy)==3)
            # A corrupted pending payload must never pass as the originally reviewed snapshot.
            created=await call(owner,'POST','/article/create',json=payload('内容校验','完整待审正文'));corrupt=created['articleId'];article_ids.append(corrupt)
            cedit=await call(owner,'GET',f'/article/{corrupt}/edit');crid=cedit['revisionId']
            original=await scalar('SELECT payload FROM article_revision WHERE revision_id=:id',id=crid)
            await db.execute("UPDATE article_revision SET payload=JSON_SET(payload,'$.content','<p>被篡改的正文</p>') WHERE revision_id=:id",{'id':crid})
            await call(manager,'POST',f'/admin/reviews/{crid}',409,json={'decision':'approve'})
            check('corrupted_snapshot_cannot_be_approved',await scalar('SELECT COUNT(*) FROM article_info WHERE article_id=:id',id=corrupt)==0)
            check('failed_approval_creates_no_result_notice',await scalar('SELECT COUNT(*) FROM notification WHERE user_id=:uid AND target_id=:rid',uid=author,rid=crid)==0)
            await db.execute('UPDATE article_revision SET payload=:p WHERE revision_id=:id',{'id':crid,'p':original})
            await call(owner,'DELETE',f'/article/{corrupt}')
            await call(manager,'POST',f'/admin/reviews/{crid}',404,json={'decision':'approve'})
            check('deleted_article_cannot_be_reviewed',not any(r['articleId']==corrupt for r in (await call(manager,'GET','/admin/reviews'))['records']))
            # Concurrent author writes share one expected immutable head.
            created=await call(owner,'POST','/article/create',json=payload('并发编辑','版本草稿',0));race=created['articleId'];article_ids.append(race)
            redit=await call(owner,'GET',f'/article/{race}/edit');rhead=redit['revisionId']
            draft_count=await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id',id=race)
            for n in range(20):
                current=await call(owner,'GET',f'/article/{race}/edit')
                updated=await call(owner,'PUT',f'/article/{race}',json={**payload('连续保存','正文'+str(n),0,current['revisionId']),'expectedLockVersion':current['lockVersion']})
                assert updated['revisionId']==rhead
            check('twenty_saves_reuse_one_working_draft',await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id',id=race)==draft_count)
            check('working_draft_never_creates_info',await scalar('SELECT COUNT(*) FROM article_info WHERE article_id=:id',id=race)==0)
            current=await call(owner,'GET',f'/article/{race}/edit')
            unchanged=await call(owner,'PUT',f'/article/{race}',json={**payload('连续保存','正文19',0,rhead),'expectedLockVersion':current['lockVersion']})
            check('identical_save_does_not_increment_lock',unchanged['lockVersion']==current['lockVersion'])
            await call(owner,'PUT',f'/article/{race}',409,json={**payload('旧AI结果','旧正文',0,rhead),'expectedLockVersion':redit['lockVersion']})
            check('same_revision_stale_lock_cannot_overwrite',True)
            redit=await call(owner,'GET',f'/article/{race}/edit')
            results=await asyncio.gather(*(owner.put(f'/article/{race}' ,json={**payload('并发编辑','仅一个写入成功',0,rhead),'expectedLockVersion':redit['lockVersion']}) for _ in range(10)))
            codes=[r.json()['code'] for r in results];check('concurrent_author_writes_preserve_one_head',codes.count(200)==1 and codes.count(409)==9)
            await call(owner,'POST',f'/article/{race}/publish',json={'expectedRevisionId':(await call(owner,'GET',f'/article/{race}/edit'))['revisionId']})
            check('submit_freezes_without_copying_body',await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id',id=race)==draft_count)
            rhead=(await call(owner,'GET',f'/article/{race}/edit'))['revisionId']
            await db.execute('UPDATE article_revision SET required_level=1 WHERE article_id=:id',{'id':race})
            results=await asyncio.gather(manager.post(f'/admin/reviews/{rhead}',json={'decision':'approve'}),owner.post(f'/article/{race}/revisions/{rhead}/withdraw'))
            codes=[r.json()['code'] for r in results];report['approval_withdrawal_codes']=codes;print('Approval/withdrawal results: '+str(codes),flush=True);check('approval_and_withdrawal_have_one_winner',sorted(codes)==[200,409])
            race_codes=[]
            for round_no in range(10):
                current=await call(owner,'GET',f'/article/{race}/edit')
                pending=await call(owner,'PUT',f'/article/{race}',json=payload('竞争回合'+str(round_no),'公开与撤回互斥检查',1,current['revisionId']))
                rid=pending['revisionId']
                responses=await asyncio.gather(manager.post(f'/admin/reviews/{rid}',json={'decision':'approve'}),owner.post(f'/article/{race}/revisions/{rid}/withdraw'))
                race_codes.append([r.json()['code'] for r in responses])
            report['repeated_approval_withdrawal_codes']=race_codes
            check('ten_repeated_approval_withdrawal_races_are_exclusive',all(sorted(c)==[200,409] for c in race_codes))
            check('author_count_matches_published_projection',await scalar('SELECT article_count FROM user_info WHERE user_id=:id',id=author)==await scalar('SELECT COUNT(*) FROM article_info WHERE user_id=:id AND status=1 AND deleted=0',id=author))
            terminal=await scalar('SELECT COUNT(*) FROM article_revision WHERE author_id=:uid AND reviewed_at IS NOT NULL AND state IN(2,3)',uid=author)
            check('every_committed_result_has_exactly_one_notice',await scalar('SELECT COUNT(*) FROM notification WHERE user_id=:uid AND type IN(6,7)',uid=author)==terminal)
            # Newer ordinary notices must not hide the review category after pagination.
            for _ in range(24):
                await db.execute('''INSERT INTO notification(notification_id,user_id,sender_id,sender_nickname,type,content,is_read,create_time)
                    VALUES(:id,:uid,:sender,'隔离测试',1,'普通评论',0,NOW())''',{'id':ids.next_id(),'uid':author,'sender':foreign})
            filtered=await call(owner,'GET','/notification/list',params={'type':6,'size':2})
            check('review_filter_is_applied_before_pagination',filtered['total']==terminal and len(filtered['records'])==min(2,terminal) and all(n['type'] in [6,7] for n in filtered['records']))
            await call(owner,'POST',f'/notification/{rejected_notification}/read')
            unread=await call(owner,'GET','/notification/list',params={'type':6,'unreadOnly':True,'size':100})
            check('review_notice_can_be_marked_read',unread['total']==terminal-1 and all(n['isRead']==0 for n in unread['records']))
            await call(owner,'POST','/notification/read-all')
            check('all_notices_mark_read',(await call(owner,'GET','/notification/unread-count'))==0 and (await call(owner,'GET','/notification/list',params={'unreadOnly':True}))['total']==0)
            await call(owner,'GET','/notification/list',400,params={'type':99});check('invalid_notification_filter_is_rejected',True)
            if '--preview' in sys.argv:
                preview=payload('等待管理员审核','这是独立提交的新版本。旧版在审核期间继续公开。',1,new_id)
                preview.update(title='Redis 与 MySQL 双写场景下的缓存一致性工程方案',summary='对比 Cache Aside、延迟双删与消息补偿，明确各种方案的适用边界。此次修改补充了监控与重试策略，审核期间旧版继续公开。')
                modified=await call(owner,'PUT',f'/article/{aid}',json=preview)
                # Disposable examples for desktop/mobile UI checks; cleaned with the same fixture guard.
                for title,state in [('缓存一致性：双写场景下的取舍与补偿',0),('RAG 实践指南：从原理到落地',3),('Spring Boot 入门：从第一个接口开始',4)]:
                    preview=payload(title,'用于验证卡片布局与审核状态的隔离样例。',0)
                    preview.update(title=title,summary='从实际问题出发，梳理核心原理、常见误区和实现步骤。结合代码示例说明方案选择与边界处理，让读者能够理解并在项目中实践。'*3)
                    created=await call(owner,'POST','/article/create',json=preview)
                    preview_id=created['articleId'];article_ids.append(preview_id)
                    if state:
                        preview_head=(await call(owner,'GET',f'/article/{preview_id}/edit'))['revisionId']
                        pending=await call(owner,'POST',f'/article/{preview_id}/publish',json={'expectedRevisionId':preview_head})
                        if state==3:await call(manager,'POST',f'/admin/reviews/{pending["revisionId"]}',json={'decision':'reject','reason':'请补充向量检索的实际示例，并说明相似度阈值的选择依据。'})
                        else:await call(owner,'POST',f'/article/{preview_id}/revisions/{pending["revisionId"]}/withdraw')
                print(f'Preview admin: {marker}-admin@sample.invalid / {password}',flush=True)
                print(f'Preview author: {marker}-author@sample.invalid / {password}',flush=True)
                print(f'Preview article: {aid}',flush=True)
                await asyncio.to_thread(input,'Press Enter after browser QA to clean up fixtures. ')
    finally:
        for aid in article_ids:
            if not await scalar('SELECT COUNT(*) FROM article_revision WHERE article_id=:id AND author_id=:uid',id=aid,uid=author) and not await scalar('SELECT COUNT(*) FROM article_info WHERE article_id=:id AND user_id=:uid AND category_id=:cat',id=aid,uid=author,cat=cat):continue
            await db.execute('DELETE FROM article_tag_relation WHERE article_id=:id',{'id':aid})
            for table in ['article_review_log','article_revision','article_index_outbox','article_read_receipt']:
                await db.execute(f'DELETE FROM {table} WHERE article_id=:id',{'id':aid})
            await db.execute('DELETE FROM admin_operation_log WHERE target_id=:id AND admin_user_id=:uid',{'id':aid,'uid':admin})
            await db.execute('DELETE FROM article_info WHERE article_id=:id AND user_id=:uid',{'id':aid,'uid':author})
        for uid in [admin,author,foreign]:
            if await scalar('SELECT COUNT(*) FROM user_info WHERE user_id=:id AND person_introduction=:marker',id=uid,marker=marker)!=1:continue
            await db.execute('DELETE FROM notification WHERE user_id=:id',{'id':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:id AND person_introduction=:marker',{'id':uid,'marker':marker})
        await db.execute('DELETE FROM category WHERE category_id=:id AND category_name=:marker',{'id':cat,'marker':marker})
        es=BaseEsClient().client
        try:
            if article_ids:
                await es.delete_by_query(index='article',query={'ids':{'values':article_ids}},refresh=True,conflicts='proceed')
                await es.delete_by_query(index='article_vectors',query={'terms':{'article_id':article_ids}},refresh=True,conflicts='proceed')
        finally:await es.close();await db.disconnect()
        report['cleanup_complete']=True;output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(output,flush=True)
if __name__=='__main__':asyncio.run(main())
