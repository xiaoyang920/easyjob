"""One real model-backed chat through the website, with a disposable identity."""
import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import jwt
import httpx
from redis.asyncio import Redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.config import settings
from evaluation.context_extended_live import resources, identity, login, stream, cleanup


async def main():
    async with resources() as (saver, client):
        fixture = await identity()
        sid = None
        try:
            await login(client, fixture)
            claims = jwt.decode(client.headers['Authorization'][7:], options={'verify_signature': False})
            sid = claims['sid']
            request_id = str(uuid4())
            started = time.monotonic()
            frames = await stream(client, '/api/agent/chat/stream', {
                'message': '这是一次聊天连通性测试，只回复“直连验证成功”。不要调用工具、检索、修改记忆或写文章。',
                'requestId': request_id,
            })
            elapsed = round((time.monotonic() - started) * 1000)
            run = await db.fetch_one('SELECT run_id,conversation_id,status,auth_sid,auth_version FROM agent_run WHERE user_id=:uid AND request_id=:request',
                {'uid': fixture['user_id'], 'request': request_id})
            assert run and run['status'] == 'succeeded', 'Chat did not complete successfully'
            assert run['auth_sid'] == sid and run['auth_version'] == claims['ver'], 'Run identity not preserved'
            assert any(frame.startswith('__RUN_ID__:') for frame in frames), 'Missing SSE run identity'
            response = await client.get(f"/api/agent/conversations/{run['conversation_id']}/messages?limit=20")
            response.raise_for_status()
            messages = response.json()['data']['items']
            assert any(m['role'] == 'assistant' and '直连验证成功' in m['content'] for m in messages), 'Persisted answer missing'
            assert any('直连验证成功' in frame for frame in frames), 'Answer missing from SSE'
            report = {'passed': True, 'real_chat_requests': 1, 'run_status': run['status'],
                      'session_bound': True, 'sse_answer_and_history_verified': True, 'elapsed_ms': elapsed}
            (ROOT/'temp/agent-direct-chat-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            # Only this disposable account's work may be cancelled or removed.
            for row in await db.fetch_all("SELECT conversation_id FROM agent_run WHERE user_id=:uid AND status IN ('running','awaiting_approval')", {'uid': fixture['user_id']}):
                await client.post(f"/api/agent/chat/{row['conversation_id']}/cancel")
            await cleanup(client, saver, fixture)
            redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                          password=settings.REDIS_PASSWORD or None)
            try:
                if sid:
                    await redis.delete('auth:v2:session:' + sid)
                await redis.delete('auth:v2:devices:' + str(fixture['user_id']))
            finally:
                await redis.aclose()
            await db.execute('DELETE FROM auth_audit WHERE actor_id=:uid OR target_id=:uid', {'uid': fixture['user_id']})
            await db.execute('DELETE FROM auth_outbox WHERE user_id=:uid', {'uid': fixture['user_id']})


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        detail = str(error) if isinstance(error, AssertionError) else (
            f'{error.request.method} {error.request.url.path} status={error.response.status_code}'
            if isinstance(error, httpx.HTTPStatusError) else 'inspect sanitized service logs')
        print('Direct chat smoke failed:', type(error).__name__, detail)
        raise SystemExit(1)
