"""Local HTTP + SQL + XLSX probe; creates isolated users/articles/daily readings.
Run python -m evaluation.admin_statistics; optional --keep-ui then --cleanup.
"""
import argparse
import os
import asyncio
import io
import json
import math
import zipfile
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
import httpx
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.fixture_cleanup import revoke_sessions

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'temp/admin-statistics-fixtures.json'
PASSWORD='Local-statistics-probe-2026!'

async def cleanup(fixtures):
    for user in fixtures:
        uid=int(user['id'])
        if await db.fetch_val('SELECT email FROM user_info WHERE user_id=:uid',{'uid':uid})!=user['email']:
            raise RuntimeError('Fixture identity changed; refusing deletion')
        # Only this explicitly marked fixture owner has articles created by this probe.
        articles=await db.fetch_all('SELECT article_id,title FROM article_info WHERE user_id=:uid',{'uid':uid})
        if any(not r['title'].startswith('[统计测试]') for r in articles):
            raise RuntimeError('Unexpected article on fixture owner; refusing deletion')
        drafts=await db.fetch_all("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.title')) AS title FROM article_revision WHERE author_id=:uid",{'uid':uid})
        if any(not r['title'].startswith('[统计测试]') for r in drafts):
            raise RuntimeError('Unexpected revision on fixture owner; refusing deletion')
        await db.execute('DELETE FROM article_revision WHERE author_id=:uid',{'uid':uid})
        await db.execute('DELETE FROM article_info WHERE user_id=:uid',{'uid':uid})
        await db.execute('DELETE FROM user_reading_daily WHERE user_id=:uid',{'uid':uid})
        await db.execute('DELETE FROM user_reading_progress WHERE user_id=:uid',{'uid':uid})
        await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email',{'uid':uid,'email':user['email']})
    await revoke_sessions([user['id'] for user in fixtures])

def workbook_rows(content,sheet=2):
    ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        sheets=ET.fromstring(book.read('xl/workbook.xml')).findall('x:sheets/x:sheet',ns)
        assert [s.attrib['name'] for s in sheets]==['统计说明','每日趋势','文章状态','阅读等级']
        shared=[]
        if 'xl/sharedStrings.xml' in book.namelist():
            shared=[''.join(node.itertext()) for node in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('x:si',ns)]
        rows=[]
        for row in ET.fromstring(book.read(f'xl/worksheets/sheet{sheet}.xml')).findall('x:sheetData/x:row',ns):
            values=[]
            for cell in row.findall('x:c',ns):
                value=cell.findtext('x:v',default='',namespaces=ns)
                if cell.attrib.get('t')=='s': value=shared[int(value)]
                elif cell.attrib.get('t')=='inlineStr': value=''.join(cell.find('x:is',ns).itertext())
                values.append(value)
            rows.append(values)
        return rows

async def article_counts(source='all'):
    """Count private workspaces and public projections as separate populations."""
    published=await db.fetch_all('SELECT article_id,status,data_source FROM article_info WHERE deleted=0')
    workspaces=await db.fetch_all('SELECT article_id,data_source FROM article_revision WHERE deleted=0 AND is_current=1 AND state IN(0,1,3,4)')
    # A published article's working copy does not add a second article.
    public_ids={r['article_id'] for r in published if r['status'] in (1,2)}
    deleted_ids={r['article_id'] for r in await db.fetch_all('SELECT article_id FROM article_info WHERE deleted<>0')}
    included=lambda row: source=='all' or row['data_source']==source
    return {
        '未公开':len({r['article_id'] for r in workspaces if included(r) and r['article_id'] not in public_ids|deleted_ids}),
        '已发布':sum(r['status']==1 for r in published if included(r)),
        '已下架':sum(r['status']==2 for r in published if included(r)),
    }

async def run(args):
    assert db.url.hostname in {'localhost','127.0.0.1','::1'},'Local database only'
    await db.connect()
    if args.cleanup:
        try:
            await cleanup(json.loads(MANIFEST.read_text(encoding='utf-8')));MANIFEST.unlink();print('Statistics fixtures cleaned.')
        finally: await db.disconnect()
        return
    if MANIFEST.exists():
        await db.disconnect();raise RuntimeError('Existing fixtures: run --cleanup first')
    marker=uuid4().hex[:12];ids=SnowflakeGenerator(worker_id=28)
    fixtures=[{'id':str(ids.next_id()),'email':f'statistics-{role}-{marker}@example.invalid','role':role,'name':name}
              for role,name in [(2,'统计测试管理员'),(1,'统计测试读者')]]
    created=[]
    async with httpx.AsyncClient(base_url=os.getenv('EASYJOB_TEST_API','http://127.0.0.1:8080'),timeout=20,trust_env=False) as client:
        async def call(path,token,code=200):
            response=await client.get(path,headers={'Authorization':f'Bearer {token}'})
            if path.startswith('/api/admin/statistics/export') and code==200:return response
            result=response.json();assert result['code']==code,(path,response.status_code,result.get('message'))
            return result.get('data')
        try:
            for user in fixtures:
                await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                    VALUES(:id,:name,:email,:password,NOW(),2,1,0,0,1,:role,0,0,0)""",{**user,'id':int(user['id']),'password':PASSWORD})
                created.append(user)
                client.cookies.clear()
                login=await client.post('/api/auth/login',json={'email':user['email'],'password':PASSWORD})
                assert login.json()['code']==200
                user['token']=login.json()['data']['token']
            token,ordinary=fixtures[0]['token'],fixtures[1]['token'];uid=int(fixtures[1]['id'])
            for path in ['/api/admin/statistics','/api/admin/statistics/export']:await call(path,ordinary,403)
            for days in [0,1,365]:await call(f'/api/admin/statistics?days={days}',token,400)
            for source in ['unknown',"business' OR 1=1 --"]:
                await call('/api/admin/statistics?'+urlencode({'source':source}),token,400)
            today=(await call('/api/admin/statistics?days=7',token))['to']
            today=date.fromisoformat(today);yesterday=today-timedelta(days=1)
            for state in [1,2]:
                aid=ids.next_id()
                await db.execute("""INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,view_count,like_count,collect_count,comment_count,share_count,status,is_top,is_essence,is_original,publish_time,create_time,update_time,deleted,required_level)
                    VALUES(:id,:uid,:title,'statistics probe','<p>isolated fixture</p>',1,0,0,0,0,0,:state,0,0,1,NOW(),NOW(),NOW(),0,0)""",{'id':aid,'uid':uid,'title':f'[统计测试] {marker} {state}','state':state})
            draft=await client.post('/api/article/create',headers={'Authorization':f'Bearer {ordinary}'},json={
                'title':f'[统计测试] {marker} draft','content':'<p>private statistics fixture</p>','contentType':1,'status':0})
            draft_result=draft.json();assert draft_result['code']==200,draft_result.get('message')
            draft_id=int(draft_result['data']['articleId'])
            assert await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE article_id=:id',{'id':draft_id})==0
            assert await db.fetch_val('SELECT COUNT(*) FROM article_revision WHERE article_id=:id AND author_id=:uid AND is_current=1 AND state=0 AND deleted=0',{'id':draft_id,'uid':uid})==1
            for day,millis in [(today,60000),(yesterday,120000)]:
                await db.execute('INSERT INTO user_reading_daily(user_id,read_day,total_millis) VALUES (:uid,:day,:millis)',{'uid':uid,'day':day,'millis':millis})
            await db.execute('INSERT INTO user_reading_progress(user_id,total_millis,earned_level) VALUES (:uid,3600000,1)',{'uid':uid})
            checks=['ordinary statistics/export forbidden','invalid/unbounded ranges rejected','new private draft exists only in article_revision']
            for days in [7,30,90]:
                report=await call(f'/api/admin/statistics?days={days}&source=all',token)
                assert len(report['daily'])==days and report['to']==str(today)
                assert report['from']==str(today-timedelta(days=days-1))
                bounds={'start':report['from'],'end':report['to']}
                users_by_day={str(r['day']):int(r['amount']) for r in await db.fetch_all('SELECT DATE(join_time) AS day,COUNT(*) AS amount FROM user_info WHERE join_time>=:start AND join_time<DATE_ADD(:end,INTERVAL 1 DAY) GROUP BY DATE(join_time)',bounds)}
                articles_by_day={str(r['day']):int(r['amount']) for r in await db.fetch_all('SELECT DATE(publish_time) AS day,COUNT(*) AS amount FROM article_info WHERE deleted=0 AND status IN (1,2) AND publish_time>=:start AND publish_time<DATE_ADD(:end,INTERVAL 1 DAY) GROUP BY DATE(publish_time)',bounds)}
                assert report['periodNewUsers']==sum(users_by_day.values())
                assert report['periodNewArticles']==sum(articles_by_day.values())
                assert report['periodReadingUsers']==await db.fetch_val('SELECT COUNT(DISTINCT d.user_id) FROM user_reading_daily d JOIN user_info u ON u.user_id=d.user_id WHERE d.read_day>=:start AND d.read_day<=:end AND d.total_millis>0',bounds)
                for row in report['daily']:
                    assert row['newUsers']==users_by_day.get(row['date'],0)
                    assert row['newArticles']==articles_by_day.get(row['date'],0)
                sql_total=await db.fetch_val('SELECT SUM(d.total_millis) FROM user_reading_daily d JOIN user_info u ON u.user_id=d.user_id WHERE d.read_day>=:start AND d.read_day<=:end AND d.total_millis>0',{'start':report['from'],'end':report['to']})
                assert report['periodReadingSeconds']==float(sql_total)/1000
                assert sum(r['count'] for r in report['levels'])==await db.fetch_val('SELECT COUNT(*) FROM user_info')
                expected_articles=await article_counts()
                assert {r['name']:r['count'] for r in report['articles']}==expected_articles,(report['articles'],expected_articles)
                assert report['periodReadingSeconds']>=180
                exported=await call(f'/api/admin/statistics/export?days={days}&source=all',token)
                assert exported.status_code==200 and exported.headers['content-type'].startswith('application/vnd.openxmlformats')
                assert 'attachment;' in exported.headers['content-disposition'] and 'no-store' in exported.headers['cache-control']
                rows=workbook_rows(exported.content);assert len(rows)==days+1
                for source,row in zip(report['daily'],rows[1:]):
                    assert row[0]==source['date']
                    assert float(row[1])==source['newUsers'] and float(row[2])==source['newArticles']
                    assert float(row[3])==source['readingMillis']/1000 and float(row[4])==source['readingUsers']
                (ROOT/f'temp/admin-statistics-{days}days.xlsx').write_bytes(exported.content)
                checks.append(f'{days}-day SQL/JSON/XLSX dates and values match')
            for source,label in [('business','真实业务'),('evaluation','评测样例')]:
                report=await call(f'/api/admin/statistics?days=7&source={source}',token)
                assert report['source']==source
                expected_articles=await article_counts(source)
                assert {r['name']:r['count'] for r in report['articles']}==expected_articles,(source,report['articles'],expected_articles)
                assert sum(r['count'] for r in report['levels'])==await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE data_source=:source',{'source':source})
                exported=await call(f'/api/admin/statistics/export?days=7&source={source}',token)
                explanation={r[0]:r[1] for r in workbook_rows(exported.content,1)[1:]}
                assert explanation['数据范围']==label and float(explanation['首次发布文章'])==report['periodNewArticles']
                assert float(explanation['有效阅读秒数'])==report['periodReadingSeconds']
                for day,row in zip(report['daily'],workbook_rows(exported.content)[1:]):
                    assert float(row[1])==day['newUsers'] and float(row[2])==day['newArticles'] and float(row[3])==day['readingMillis']/1000
                checks.append(f'{source} SQL/JSON/XLSX source and values match')
            default=await call('/api/admin/statistics?days=7',token)
            assert default['source']=='business'
            await db.execute('UPDATE user_info SET status=0 WHERE user_id=:uid',{'uid':uid})
            disabled=await call('/api/admin/statistics?days=7',token)
            assert disabled['periodReadingSeconds']==default['periodReadingSeconds']
            await db.execute("UPDATE user_info SET data_source='evaluation' WHERE user_id=:uid",{'uid':uid})
            filtered=await call('/api/admin/statistics?days=7',token)
            assert math.isclose(filtered['periodReadingSeconds'],default['periodReadingSeconds']-180,abs_tol=1e-9)
            checks.append('default excludes evaluation data; disabled business readers remain included')
            (ROOT/'temp/admin-statistics-results.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'scope':'isolated local fixtures, actual SQL + HTTP + XLSX, no model calls'},indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'report':'temp/admin-statistics-results.json'}))
            if args.keep_ui:
                MANIFEST.write_text(json.dumps([{k:v for k,v in u.items() if k!='token'} for u in created],ensure_ascii=False),encoding='utf-8')
                print('UI fixture email: '+fixtures[0]['email'])
        finally:
            if not args.keep_ui or not MANIFEST.exists():await cleanup(created)
            await db.disconnect()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--keep-ui',action='store_true');parser.add_argument('--cleanup',action='store_true')
    asyncio.run(run(parser.parse_args()))
