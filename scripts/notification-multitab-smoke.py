"""Read-only loopback verification: two SSE tabs survive and public/protected APIs respond."""
import asyncio,json,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from evaluation.local_samples import local_token

async def frame(lines,event):
    async for line in lines:
        if event=='heartbeat' and line.startswith(':'):return
        if line.replace(' ','')=='event:'+event:
            async for trailing in lines:
                if not trailing:return
    raise AssertionError('A tab was disconnected when another tab connected')

async def main():
    assert settings.MYSQL_HOST in ('127.0.0.1','localhost','::1')
    await db.connect()
    try:uid=await db.fetch_val('SELECT user_id FROM user_info WHERE status=1 AND COALESCE(auth_version,0)=0 ORDER BY user_id LIMIT 1')
    finally:await db.disconnect()
    assert uid
    token=local_token(uid);checks={}
    async with httpx.AsyncClient(timeout=35,trust_env=False) as first,httpx.AsyncClient(timeout=35,trust_env=False) as second:
        async with first.stream('GET','http://127.0.0.1:8090/api/notification/stream',params={'token':token}) as a:
            assert a.status_code==200
            lines_a=a.aiter_lines();await frame(lines_a,'connected')
            async with second.stream('GET','http://127.0.0.1:8090/api/notification/stream',params={'token':token}) as b:
                assert b.status_code==200
                lines_b=b.aiter_lines();await frame(lines_b,'connected')
                await asyncio.wait_for(asyncio.gather(frame(lines_a,'heartbeat'),frame(lines_b,'heartbeat')),30)
                checks['two_tabs_keep_independent_notification_connections']=True
        for path in ['article/list','user/space/'+str(uid),'agent/library','chat/conversations','notification/unread-count','agent/run-overview']:
            response=await first.get('http://127.0.0.1:3000/api/'+path,headers={'Authorization':'Bearer '+token})
            assert response.status_code==200 and response.json().get('code')==200,(path,response.status_code)
            checks[path]=True
    (ROOT/'logs/notification-multitab-live.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':asyncio.run(main())
