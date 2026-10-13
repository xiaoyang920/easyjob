"""Read-only loopback checks of the gateway, discovery and both real RPC directions."""
import asyncio
import json
import sys
import time
from pathlib import Path
import httpx
import grpc
import websockets

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from app.rpc import blog_client
from app.rpc.codec import decode
from app.rpc.discovery import catalog
from app.rpc.generated import easyjob_rpc_pb2 as pb,easyjob_rpc_pb2_grpc as api
from evaluation.local_samples import local_token

async def main():
    assert settings.MYSQL_HOST in ('localhost','127.0.0.1','::1'),'Only local fixture databases are allowed'
    results={}
    await db.connect()
    try:
        uid=await db.fetch_val('SELECT user_id FROM user_info WHERE status=1 ORDER BY user_id LIMIT 1')
        assert uid,'A local test user is required'
        token=local_token(uid)
        async with httpx.AsyncClient(timeout=25,trust_env=False) as client:
            for name,port in [('gateway',8090),('frontend_proxy',3000)]:
                r=await client.get(f'http://127.0.0.1:{port}/api/article/list')
                assert r.status_code==200 and r.json()['code']==200,(name,r.status_code)
                results[name]=True
            for service in ('easyjob-blog','easyjob-agent'):
                r=await client.get(f'http://127.0.0.1:8500/v1/health/service/{service}?passing=true')
                assert r.json(),service
                results[service+'_discovered']=len(r.json())
            headers={'Authorization':'Bearer '+token}
            for path in ('/agent/conversations','/agent/run-overview','/agent/memory'):
                r=await client.get('http://127.0.0.1:8090/api'+path,headers=headers)
                assert r.status_code==200 and r.json().get('code')==200,(path,r.status_code,r.text[:150])
                results[path]=True
            admin=await db.fetch_val("SELECT user_id FROM user_info WHERE role=2 AND status=1 ORDER BY user_id LIMIT 1")
            if admin:
                admin_headers={'Authorization':'Bearer '+local_token(admin)}
                for path in ('/admin/agent-metrics?source=all','/admin/operations'):
                    r=await client.get('http://127.0.0.1:8090/api'+path,headers=admin_headers)
                    assert r.status_code==200 and r.json().get('code')==200,(path,r.status_code,r.text[:150])
                    results[path]=True
            r=await client.get('http://127.0.0.1:8090/api/article/list',headers={'Authorization':'Bearer invalid'})
            assert r.status_code==401;results['invalid_jwt_rejected']=True
            r=await client.get('http://127.0.0.1:8090/internal/agent/drafts')
            assert r.status_code==404;results['internal_route_not_public']=True
            run=await db.fetch_one("SELECT run_id FROM agent_run WHERE user_id=:uid AND status IN ('succeeded','failed','cancelled','expired') ORDER BY created_at DESC LIMIT 1",{'uid':uid})
            if run:
                start=time.monotonic();frames=[]
                async with client.stream('GET',f"http://127.0.0.1:8090/api/agent/runs/{run['run_id']}/events",headers=headers) as stream:
                    assert stream.status_code==200
                    async for line in stream.aiter_lines():
                        if line:frames.append(line)
                assert any('[DONE]' in f or '[ERROR]' in f for f in frames),frames[-3:]
                results['real_run_sse_frames']=len(frames)
                results['sse_seconds']=round(time.monotonic()-start,3)
            # Never send a chat message: only open and close the authenticated socket.
            async with websockets.connect('ws://127.0.0.1:8090/ws/chat?token='+token,
                    origin='http://127.0.0.1:3000',open_timeout=8):
                results['websocket_handshake']=True
        aid=await db.fetch_val('SELECT article_id FROM article_info WHERE status=1 AND deleted=0 AND required_level=0 ORDER BY article_id LIMIT 1')
        rows=await blog_client.public_read('published',ids=[aid])
        assert len(rows)==1 and int(rows[0]['article_id'])==aid
        results['python_to_java_public_read']=True
        for kind,kwargs in [('tags',{'names':['Java']}),('categories',{'names':['测试']}),('authors',{'name':'__smoke_no_user__'}),
                ('comments',{'target_id':aid}),('user_articles',{'target_id':uid}),('trending',{}),('user_sources',{'ids':[uid]})]:
            assert isinstance(await blog_client.public_read(kind,**kwargs),list),kind
        results['blog_query_contracts']=7
        assert isinstance(await blog_client.maintenance('metrics'),dict)
        private=await db.fetch_val('SELECT article_id FROM article_info WHERE status<>1 OR deleted<>0 OR required_level>0 LIMIT 1')
        if private:
            assert await blog_client.public_read('published',ids=[private])==[]
            results['private_article_excluded']=True
        async with grpc.aio.insecure_channel('127.0.0.1:50051') as channel:
            stub=api.AgentRpcStub(channel)
            q=pb.AgentQuery(identity=blog_client.identity(uid),kind='metric_states',source='all',start='2026-10-01',end='2026-10-14')
            response=await stub.ServiceQuery(q,timeout=10)
            assert not response.HasField('error'),response.error
            assert isinstance(decode(response.data),list)
            q.identity.service_key='bad-key'
            response=await stub.ServiceQuery(q,timeout=10)
            assert response.error.status==401
            results['agent_query_and_service_auth']=True
        print(json.dumps(results,ensure_ascii=False,indent=2))
        (ROOT/'logs/service-split-live.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        await blog_client.close_client()
        await catalog.close()
        await db.disconnect()

if __name__=='__main__':asyncio.run(main())
