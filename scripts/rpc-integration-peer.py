"""Real gRPC peer for the opt-in Java Dubbo interoperability test (no DB or model calls)."""
import asyncio
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'python-agent'))
os.environ['DEEPSEEK_API_KEY'] = 'rpc-integration-offline-key'
os.environ['ZHIPUAI_API_KEY'] = 'rpc-integration-offline-key'
os.environ['DASHSCOPE_API_KEY'] = 'rpc-integration-offline-key'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['SERVICE_DISCOVERY_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'rpc-test-service-key-at-least-32-bytes'
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from app.config import settings
from app.rpc import server, blog_client
from app.rpc.generated import easyjob_rpc_pb2 as pb
from fastapi import HTTPException
from app.services.logging_config import current_trace_id, set_request_trace

BIG = 9007199254740993


async def serve(port, ready):
    from unittest.mock import patch
    async def query(request, uid):
        assert uid == 7
        assert current_trace_id() == 'interop-java-12345678'
        if request.kind == 'conflict':
            raise HTTPException(409, '操作版本已改变')
        return {'reply': '中文二进制 RPC', 'id': BIG, 'items': []}
    settings.AGENT_RPC_BIND = f'127.0.0.1:{port}'
    with patch('app.security.delegation.verify', return_value={}), \
            patch('app.services.service_queries.query', side_effect=query):
        rpc = await server.start_server()
        Path(ready).write_text('ready')
        try:
            while not Path(ready + '.stop').exists():
                await asyncio.sleep(.05)
        finally:
            await rpc.stop(0)


async def callback(port):
    set_request_trace(trace_id='interop-python-12345678')
    settings.BLOG_RPC_TARGET = f'127.0.0.1:{port}'
    try:
        rows = await blog_client.list_drafts(7, '中文')
        assert rows == [{'articleId': str(BIG), 'title': '中文草稿'}], rows
        data = await blog_client.read_draft(7, BIG)
        assert data['id'] == BIG and data['editable'] is True and data['empty'] == [], data
        payload = dict(runId='run', executionToken='token', articleId=str(BIG), title='中文', summary='',
            markdown='正文', html='<p>正文</p>', draftHash='a'*64, expectedRevisionId='5', expectedLockVersion=0)
        result = await blog_client.save_draft(7, payload)
        assert result['articleId'] == str(BIG), result
        payload['expectedLockVersion'] = 1
        try: await blog_client.save_draft(7, payload)
        except blog_client.ServiceError as error: assert error.status == 409
        else: raise AssertionError('Stale draft must conflict')
        settings.AGENT_SERVICE_KEY = 'wrong-service-key'
        try:
            await blog_client.call('ReadDraft', pb.DraftRequest(identity=pb.Identity(user_id=7, service_key='wrong'), article_id=BIG))
        except blog_client.ServiceError as error: assert error.status == 401
        else: raise AssertionError('Invalid identity must fail')
        print('Python -> Java Triple: passed (read/write/conflict/auth/int64)')
    finally: await blog_client.close_client()


if __name__ == '__main__':
    if sys.argv[1] == 'server': asyncio.run(serve(int(sys.argv[2]), sys.argv[3]))
    elif sys.argv[1] == 'callback': asyncio.run(callback(int(sys.argv[2])))
    else: raise SystemExit('Unknown mode')
