"""Verify RabbitMQ revocation reaches two real Blog JVMs; no live service stops."""
import asyncio
import hashlib
import json
import secrets
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt
import websockets
import yaml
from redis.asyncio import Redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.config import settings
from app.clients.mysql_client import db


def free_port():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


async def main():
    started = datetime.now(timezone.utc).isoformat()
    work = ROOT / 'temp' / ('auth-cluster-' + secrets.token_hex(4))
    work.mkdir()
    port = free_port()
    config = yaml.safe_load((ROOT / 'temp/application-runtime.yml').read_text(encoding='utf-8'))
    config['server'] = {'port':port, 'address':'127.0.0.1'}
    config['SERVICE_DISCOVERY_ENABLED'] = False
    config['spring']['cloud'] = {'consul':{'enabled':False}}
    config['spring'].setdefault('rabbitmq', {}).setdefault('listener', {}).setdefault('simple', {})['auto-startup'] = False
    config.setdefault('agent', {}).setdefault('rpc', {})['port'] = free_port()
    config.setdefault('deepseek', {}).setdefault('balance-alert', {})['enabled'] = False
    path = work / 'blog.yml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    gateway = yaml.safe_load((ROOT / 'temp/gateway-runtime.yml').read_text(encoding='utf-8'))
    signing = json.loads(Path(gateway['easyjob']['auth']['gateway-private-key-file']).read_text())
    key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(signing))
    redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, password=settings.REDIS_PASSWORD or None)
    client = httpx.AsyncClient(timeout=10, trust_env=False)
    process, uid, sid = None, None, None
    checks = []

    def expect(name, passed):
        checks.append({'name':name, 'passed':bool(passed)})
        if not passed:
            raise AssertionError(name)

    def identity(claims):
        now = int(time.time())
        value = {'iss':'easyjob-gateway', 'aud':['easyjob-blog'], 'token_use':'gateway',
                 'sub':claims['sub'], 'sid':claims['sid'], 'ver':claims['ver'], 'roles':['1'],
                 'kind':'user', 'iat':now, 'nbf':now, 'exp':now+15, 'jti':str(uuid.uuid4()),
                 'method':'GET', 'path':'/ws/chat', 'trace':str(uuid.uuid4())}
        return jwt.encode(value, key, algorithm='RS256', headers={'kid':signing['kid']})

    await db.connect()
    try:
        with (work / 'blog.log').open('wb') as output:
            # app.config loads local .env values into this Python process. CLI
            # overrides prevent them enabling discovery or balance polling in
            # the disposable Java instance, above environment precedence.
            process = await asyncio.create_subprocess_exec('D:/jdk/bin/java.exe', '-Xmx512m', '-jar', str(ROOT / 'target/easyjob-0.0.1-SNAPSHOT.jar'), '--spring.config.additional-location=file:' + path.as_posix(), '--SERVICE_DISCOVERY_ENABLED=false', '--deepseek.balance-alert.enabled=false', cwd=ROOT, stdout=output, stderr=output)
            deadline = time.monotonic() + 80
            while True:
                if process.returncode is not None or time.monotonic() > deadline:
                    raise RuntimeError('Second Blog startup failed; inspect ignored logs')
                try:
                    if (await client.get(f'http://127.0.0.1:{port}/actuator/health')).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
            print('Second isolated Blog instance ready.', flush=True)
            email, password, code = 'auth-smoke-' + secrets.token_hex(5) + '@example.invalid', 'Auth-test-' + secrets.token_hex(12), '123456'
            digest = hashlib.sha256(email.encode()).hexdigest()
            await redis.set('auth:v2:code:login:' + digest, hashlib.sha256((email+':'+code).encode()).hexdigest(), ex=600)
            response = await client.post('http://127.0.0.1:8090/api/auth/register', json={'email':email,'password':password,'code':code,'nickName':'auth-'+secrets.token_hex(5)})
            expect('cluster_fixture_registration', response.status_code == 200)
            token = response.json()['data']['token']
            claims = jwt.decode(token, options={'verify_signature':False})
            uid, sid = int(claims['sub']), claims['sid']
            # The fixture acts as the trusted gateway using its real test-held
            # signing key. External callers cannot construct this assertion.
            async with websockets.connect('ws://127.0.0.1:8080/ws/chat', additional_headers={'X-Easyjob-Identity':identity(claims)}, proxy=None) as first, websockets.connect(f'ws://127.0.0.1:{port}/ws/chat', additional_headers={'X-Easyjob-Identity':identity(claims)}, proxy=None) as second:
                await asyncio.wait_for(first.recv(), 5)
                await asyncio.wait_for(second.recv(), 5)
                expect('same_session_connected_on_two_blog_instances', True)
                # Password reset emits the SQL outbox/Rabbit event, unlike
                # logout's best-effort Redis broadcast.
                await redis.set('auth:v2:code:reset:' + digest, hashlib.sha256((email+':'+code).encode()).hexdigest(), ex=600)
                started_revoke = time.monotonic()
                response = await client.post('http://127.0.0.1:8090/api/auth/password/reset', json={'email':email,'code':code,'password':password+'x'})
                expect('password_reset_commits_revocation_outbox', response.status_code == 200)

                async def closed(channel):
                    try:
                        while True:
                            await channel.recv()
                    except websockets.exceptions.ConnectionClosed:
                        return

                await asyncio.wait_for(asyncio.gather(closed(first), closed(second)), 8)
                expect('rabbit_revocation_closes_both_blog_instances', True)
                elapsed = round((time.monotonic()-started_revoke)*1000, 2)
                deadline = time.monotonic()+6
                while not await db.fetch_val('SELECT COUNT(*) FROM auth_outbox WHERE user_id=:uid AND published_at IS NOT NULL', {'uid':uid}):
                    if time.monotonic()>deadline:
                        raise AssertionError('revocation_outbox_not_acknowledged')
                    await asyncio.sleep(.2)
                expect('outbox_publish_acknowledged', True)
                response = await client.get('http://127.0.0.1:8090/api/account/sessions', headers={'Authorization':'Bearer '+token})
                expect('revoked_cluster_session_cannot_make_new_request', response.status_code==401)
            report = {'started_at':started, 'completed_at':datetime.now(timezone.utc).isoformat(), 'passed':len(checks), 'checks':checks, 'blog_instances':2, 'both_connections_closed_ms':elapsed, 'model_calls':0, 'emails_sent':0}
            (ROOT / 'temp/unified-auth-cluster-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'passed':len(checks), 'both_connections_closed_ms':elapsed,'model_calls':0,'emails_sent':0}), flush=True)
    finally:
        if process and process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 12)
        if sid:
            await redis.delete('auth:v2:session:'+sid)
        if uid:
            await redis.delete('auth:v2:devices:'+str(uid))
            await db.execute('DELETE FROM auth_outbox WHERE user_id=:uid', {'uid':uid})
            await db.execute('DELETE FROM auth_audit WHERE target_id=:uid OR actor_id=:uid', {'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid', {'uid':uid})
        await redis.aclose()
        await client.aclose()
        await db.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Cluster auth check failed:', type(error).__name__, str(error) if isinstance(error, AssertionError) else 'inspect ignored test logs')
        raise SystemExit(1)
