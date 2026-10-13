"""Durable save reservation + signed permission + blog-owned idempotent receipt.

Cancellation wins before reservation. After reservation the short commit can
finish; timeout means unknown, not failed. A sweeper reconciles the receipt.
"""
import base64
import hashlib
import hmac
import json
import time
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.config import settings
from app.rpc import blog_client


def sign(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims, separators=(',', ':'), ensure_ascii=False).encode()).rstrip(b'=')
    signature = base64.urlsafe_b64encode(hmac.new(settings.AGENT_SERVICE_KEY.encode(), payload, hashlib.sha256).digest()).rstrip(b'=')
    return (payload + b'.' + signature).decode()


async def reserve(state, body, database=db):
    from app.services.run_repository import RunRepository
    repository = RunRepository(database)
    async with database.transaction():
        await repository._lock_conversation(state['conversation_id'], state['user_id'])
        row = await database.fetch_one('SELECT * FROM agent_run WHERE run_id=:rid AND user_id=:uid FOR UPDATE',
            {'rid': state['run_id'], 'uid': state['user_id']})
        if not row:
            raise HTTPException(409, '审批运行不存在')
        run = dict(row._mapping)
        if run['conversation_id'] != state['conversation_id']:
            raise HTTPException(409, '会话不匹配')
        result = json.loads(run.get('result_json') or '{}')
        prior = result.get('draft_commit')
        if prior:
            if prior['hash'] != body['draftHash'] or prior['aid'] != int(body['articleId']):
                raise HTTPException(409, '保存内容已改变')
            if prior['exp'] < time.time():
                raise HTTPException(409, '保存正在核对，请稍后刷新')
            return prior['permit']
        await repository.assert_executor(state['run_id'], state['execution_token'])
        if run['draft_hash'] != body['baseDraftHash']:
            raise HTTPException(409, '审批草稿版本已改变')
        claims = {'uid': state['user_id'], 'rid': state['run_id'], 'aid': int(body['articleId']),
            'hash': body['draftHash'], 'revision': body.get('expectedRevisionId') or '',
            'lock': '' if body.get('expectedLockVersion') is None else str(body['expectedLockVersion']),
            'exp': int(time.time()) + 120}
        claims['permit'] = sign(claims)
        result['draft_commit'] = claims
        await database.execute('UPDATE agent_run SET result_json=:result WHERE run_id=:rid',
            {'result': json.dumps(result), 'rid': state['run_id']})
        return claims['permit']


async def complete(uid, rid, saved, database=db):
    await database.execute("""UPDATE agent_run SET draft_article_id=:aid,draft_hash=:hash,updated_at=UTC_TIMESTAMP(6)
        WHERE run_id=:rid AND user_id=:uid AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.draft_commit.hash'))=:hash
        AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.draft_commit.aid'))=:aid""",
        {'rid': rid, 'uid': uid, 'aid': int(saved['articleId']), 'hash': saved['draftHash']})


async def abort(rid, database=db):
    await database.execute("""UPDATE agent_run SET result_json=JSON_REMOVE(result_json,'$.draft_commit')
        WHERE run_id=:rid AND draft_article_id IS NULL""", {'rid': rid})


async def reconcile(database=db):
    rows = await database.fetch_all("""SELECT run_id,user_id,result_json FROM agent_run
        WHERE draft_article_id IS NULL AND JSON_EXTRACT(result_json,'$.draft_commit') IS NOT NULL
        ORDER BY updated_at LIMIT 20""")
    for row in rows:
        r = row._mapping; intent = json.loads(r['result_json'])['draft_commit']
        try:
            saved = await blog_client.draft_receipt(r['user_id'], r['run_id'])
        except blog_client.ServiceError:
            continue
        if saved:
            await complete(r['user_id'], r['run_id'], saved, database)
        elif time.time() > intent['exp'] + 30:
            # Expired permission + Java's 20s transaction deadline: no commit can begin.
            await abort(r['run_id'], database)
            await database.execute("UPDATE agent_run SET status='failed',updated_at=UTC_TIMESTAMP(6) WHERE run_id=:rid AND draft_article_id IS NULL AND status='running'", {'rid': r['run_id']})
