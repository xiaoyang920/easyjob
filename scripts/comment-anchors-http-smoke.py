"""Exercise quote comments through the real gateway/Java/MySQL using disposable data."""
import asyncio
import json
from pathlib import Path
import secrets
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
import httpx
from app.clients.mysql_client import db


async def main():
    uid=(1<<57)+secrets.randbits(48)
    other_uid=uid+1
    aid=(1<<57)+secrets.randbits(48)
    suffix=secrets.token_hex(6)
    password='Qa-comment-'+secrets.token_hex(12)
    checks={}; sessions=[]
    await db.connect()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8090/api',timeout=30,trust_env=False) as client:
        try:
            for user_id,name in [(uid,'owner'),(other_uid,'other')]:
                await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                    VALUES(:uid,:name,:email,:password,'Disposable comment QA',NOW(),1,2,0,0,0,1,1,0,0,'evaluation')''',
                    {'uid':user_id,'name':f'批注{name}{suffix[:8]}','email':f'comment-qa-{name}-{suffix}@example.invalid','password':password})
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,content,create_time,update_time,publish_time,status,deleted,required_level,data_source)
                VALUES(:aid,:uid,'划词评论接口验收','<h2>标题</h2><p>这里是正文。</p><p>后续段落。</p>',NOW(),NOW(),NOW(),1,0,0,'evaluation')''',{'aid':aid,'uid':uid})
            async def login(name):
                # Logging into another account in one browser deliberately
                # revokes that browser's prior session. These are separate users.
                client.cookies.clear()
                response=(await client.post('/auth/login',json={'email':f'comment-qa-{name}-{suffix}@example.invalid','password':password})).json()
                assert response['code']==200,'Fixture login failed'
                credential=client.cookies.get('easyjob_refresh')
                if credential: sessions.append(credential)
                return {'Authorization':'Bearer '+response['data']['token']}
            owner=await login('owner')
            quote={'exact':'这里是正文。','start':3,'end':9,'prefix':'标题 ','suffix':' 后续段落。'}
            payload={'articleId':str(aid),'articleUserId':str(other_uid),'content':'这里可以讨论失败恢复。','quote':quote}
            result=(await client.post('/comment/create',json=payload,headers=owner)).json()
            assert result['code']==200,'Quote comment creation failed: '+str(result.get('message'))
            comment=result['data'];cid=comment['commentId']
            assert comment['quote']['exact']==quote['exact'] and len(comment['quote']['contentHash'])==64
            checks['quote_created_and_persisted']=bool(await db.fetch_val('SELECT COUNT(*) FROM article_comment_anchor WHERE comment_id=:cid',{'cid':int(cid)}))
            assert await db.fetch_val('SELECT article_user_id FROM comment WHERE comment_id=:cid',{'cid':int(cid)})==uid
            checks['server_resolves_real_author']=True
            listed=(await client.get('/comment/quotes',params={'articleId':aid})).json()
            assert listed['code']==200 and listed['data']['records'][0]['quote']['exact']==quote['exact']
            checks['anonymous_read_and_quote_round_trip']=True
            stale={**payload,'quote':{**quote,'exact':'伪造的引用','end':8}}
            rejected=(await client.post('/comment/create',json=stale,headers=owner)).json()
            assert rejected['code']==409
            assert await db.fetch_val('SELECT COUNT(*) FROM comment WHERE article_id=:aid',{'aid':aid})==1
            checks['stale_quote_rejected_without_partial_comment']=True
            second=(await client.post('/comment/create',json={**payload,'content':'同一片段的另一条评论。'},headers=owner)).json()
            assert second['code']==200
            cid2=second['data']['commentId']
            first_page=(await client.get('/comment/quote-markers',params={'articleId':aid,'size':1})).json()
            assert first_page['code']==200 and len(first_page['data']['records'])==1
            cursor=first_page['data']['nextCursor']
            assert cursor
            second_page=(await client.get('/comment/quote-markers',params={'articleId':aid,'size':1,'afterId':cursor})).json()
            assert second_page['code']==200 and len(second_page['data']['records'])==1 and not second_page['data']['nextCursor']
            ids=[first_page['data']['records'][0]['commentId'],second_page['data']['records'][0]['commentId']]
            assert set(ids)=={cid,cid2}
            checks['all_markers_use_stable_cursor_pages']=True
            selected=(await client.get('/comment/quotes',params={'articleId':aid,'ids':cid})).json()
            assert selected['code']==200 and selected['data']['total']==1 and selected['data']['records'][0]['commentId']==cid
            missing=(await client.get('/comment/quotes',params={'articleId':aid,'ids':'1'})).json()
            assert missing['code']==200 and missing['data']['total']==0
            checks['focused_threads_are_filtered_and_article_scoped']=True
            reply=(await client.post('/comment/create',json={'articleId':str(aid),'content':'回复同一段原文。','parentId':cid},headers=owner)).json()
            assert reply['code']==200 and reply['data'].get('quote') is None
            listed_replies=(await client.get('/comment/replies',params={'commentId':cid,'page':1,'size':20})).json()
            assert listed_replies['code']==200 and listed_replies['data']['total']==1
            checks['existing_reply_endpoint_works']=True
            other=await login('other')
            denied=(await client.delete('/comment/'+cid,headers=other)).json()
            assert denied['code']==403
            checks['foreign_delete_denied']=True
            ordinary=(await client.post('/comment/create',json={'articleId':str(aid),'content':'普通评论仍然可用。'},headers=owner)).json()
            assert ordinary['code']==200 and ordinary['data'].get('quote') is None, f"Ordinary comment failed: {ordinary.get('code')} {ordinary.get('message')}"
            filtered=(await client.get('/comment/quotes',params={'articleId':aid,'size':500},headers=owner)).json()
            assert filtered['code']==200 and filtered['data']['total']==2 and filtered['data']['size']==50
            checks['ordinary_comments_compatible_and_quotes_paginated']=True
            await db.execute('UPDATE article_info SET required_level=1 WHERE article_id=:aid',{'aid':aid})
            restricted=(await client.get('/comment/quotes',params={'articleId':aid})).json()
            assert restricted['code']==403
            restricted_markers=(await client.get('/comment/quote-markers',params={'articleId':aid})).json()
            restricted_selected=(await client.get('/comment/quotes',params={'articleId':aid,'ids':cid})).json()
            assert restricted_markers['code']==403 and restricted_selected['code']==403
            own=(await client.get('/comment/quotes',params={'articleId':aid},headers=owner)).json()
            assert own['code']==200
            checks['restricted_quotes_require_read_access']=True
            removed=(await client.delete('/comment/'+cid,headers=owner)).json()
            assert removed['code']==200
            assert await db.fetch_val('SELECT COUNT(*) FROM article_comment_anchor WHERE comment_id=:cid',{'cid':int(cid)})==0
            assert await db.fetch_val('SELECT COUNT(*) FROM comment WHERE parent_id=:cid',{'cid':int(cid)})==0
            checks['delete_cascades_to_anchor_and_replies']=True
        finally:
            for credential in sessions:
                await client.post('/auth/logout',headers={'X-Auth-Refresh':'1','Cookie':'easyjob_refresh='+credential})
            await db.execute('DELETE FROM comment WHERE article_id=:aid',{'aid':aid})
            await db.execute('DELETE FROM article_info WHERE article_id=:aid AND user_id=:uid',{'aid':aid,'uid':uid})
            for user_id in (uid,other_uid):
                await db.execute('DELETE FROM user_info WHERE user_id=:uid',{'uid':user_id})
            await db.disconnect()
    checks['disposable_fixture_cleaned']=True
    (ROOT/'logs/comment-anchors-http-smoke.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False))

if __name__=='__main__': asyncio.run(main())
