"""Real isolated Auth/Gateway failure and key-rotation checks; no production stops.

Uses disposable ports, private test keys and one disposable account. Only the
isolated processes connect through fault gates. No model or email calls.
"""
import asyncio
import hashlib
import json
import runpy
import secrets
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt
import yaml
from redis.asyncio import Redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.config import settings
from app.clients.mysql_client import db


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class RedisGate:
    def __init__(self):
        self.enabled = True
        self.writers = set()
        self.tasks = set()

    async def start(self):
        self.server = await asyncio.start_server(self.accept, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        upstream = None
        try:
            if not self.enabled:
                return
            upstream_reader, upstream = await asyncio.open_connection(settings.REDIS_HOST, settings.REDIS_PORT)
            self.writers.add(upstream)

            async def pump(source, target):
                while chunk := await source.read(65536):
                    target.write(chunk)
                    await target.drain()

            transfers = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(upstream_reader, writer))]
            try:
                await asyncio.wait(transfers, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for transfer in transfers:
                    transfer.cancel()
                await asyncio.gather(*transfers, return_exceptions=True)
        except (ConnectionError, OSError):
            pass
        finally:
            for stream in (writer, upstream):
                if stream:
                    stream.close()
                    self.writers.discard(stream)
            self.tasks.discard(task)

    def interrupt(self):
        self.enabled = False
        for writer in tuple(self.writers):
            writer.close()

    async def close(self):
        self.interrupt()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)


class AuthGate:
    def __init__(self, target):
        self.target = target
        self.failed = set()
        self.calls = {}
        self.client = httpx.AsyncClient(timeout=4, trust_env=False)

    async def start(self):
        self.server = await asyncio.start_server(self.accept, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def accept(self, reader, writer):
        try:
            header = await reader.readuntil(b'\r\n\r\n')
            first, *lines = header.decode('latin-1').split('\r\n')
            method, path, _ = first.split(' ')
            headers = dict(line.split(': ', 1) for line in lines if ': ' in line)
            body = await reader.readexactly(int(next((v for k, v in headers.items() if k.lower() == 'content-length'), '0')))
            self.calls[path] = self.calls.get(path, 0) + 1
            group = 'jwks' if path == '/api/auth/jwks' else 'session' if path.startswith('/internal/auth/') else 'api'
            if group in self.failed:
                status, payload = 503, b'{"code":503}'
            else:
                response = await self.client.request(method, self.target + path, headers={k:v for k,v in headers.items() if k.lower() not in ('host','connection','transfer-encoding')}, content=body)
                status, payload = response.status_code, response.content
            writer.write(f'HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode() + payload)
            await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError, httpx.HTTPError):
            pass
        finally:
            writer.close()

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        await self.client.aclose()


async def main():
    started = datetime.now(timezone.utc).isoformat()
    work = ROOT / 'temp' / ('auth-resilience-' + secrets.token_hex(4))
    work.mkdir()
    checks, processes, streams, uid, sids = [], [], [], None, set()
    auth_port, gateway_port = free_port(), free_port()
    auth_url, gateway_url = f'http://127.0.0.1:{auth_port}', f'http://127.0.0.1:{gateway_port}'
    auth_redis, gateway_redis = await RedisGate().start(), await RedisGate().start()
    proxy = await AuthGate(auth_url).start()
    redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, password=settings.REDIS_PASSWORD or None)
    client = httpx.AsyncClient(timeout=10, trust_env=False)
    generate = runpy.run_path(str(ROOT / 'scripts/generate-auth-keys.py'))['generate']
    rotate = runpy.run_path(str(ROOT / 'scripts/rotate-auth-key.py'))['main']
    generate(work / 'keys')
    auth_config = yaml.safe_load((ROOT / 'temp/auth-runtime.yml').read_text(encoding='utf-8'))
    auth_config['server'] = {'port': auth_port, 'address': '127.0.0.1'}
    auth_config['spring']['cloud'] = {'consul': {'enabled': False}}
    auth_config['spring']['data']['redis']['port'] = auth_redis.port
    auth_config['auth']['private-key-file'] = str(work / 'keys/auth-private.json')
    auth_config['auth']['cookie-secure'] = False
    (work / 'auth.yml').write_text(yaml.safe_dump(auth_config), encoding='utf-8')
    gateway_config = yaml.safe_load((ROOT / 'temp/gateway-runtime.yml').read_text(encoding='utf-8'))
    gateway_config['server'] = {'port': gateway_port, 'address': '127.0.0.1'}
    spring = gateway_config.setdefault('spring', {})
    spring.setdefault('data', {}).setdefault('redis', {})['port'] = gateway_redis.port
    cloud = spring.setdefault('cloud', {})
    cloud['consul'] = {'enabled': False}
    cloud['gateway'] = {'routes': [
        {'id': 'auth-test', 'uri': f'http://127.0.0.1:{proxy.port}', 'predicates': ['Path=/api/auth/**,/api/account/**']},
        {'id': 'blog-test', 'uri': 'http://127.0.0.1:8080', 'predicates': ['Path=/api/**']}]}
    gateway_config['easyjob']['auth']['base-url'] = f'http://127.0.0.1:{proxy.port}'
    gateway_config['easyjob']['auth']['jwks-uri'] = f'http://127.0.0.1:{proxy.port}/api/auth/jwks'
    (work / 'gateway.yml').write_text(yaml.safe_dump(gateway_config), encoding='utf-8')

    def expect(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    async def start(name, jar):
        output = (work / (name + '-' + secrets.token_hex(3) + '.log')).open('wb')
        streams.append(output)
        process = await asyncio.create_subprocess_exec('D:/jdk/bin/java.exe', '-Xmx384m', '-jar', str(ROOT / jar), '--spring.config.additional-location=file:' + (work / (name + '.yml')).as_posix(), cwd=ROOT, stdout=output, stderr=output)
        processes.append(process)
        return process

    async def ready(url, process=None, timeout=65):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process and process.returncode is not None:
                raise RuntimeError('Isolated service exited; inspect its ignored logs')
            try:
                if (await client.get(url + '/actuator/health')).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        raise RuntimeError('Isolated service readiness timeout')

    async def stop(process):
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 12)

    def remember(response):
        token = response.json()['data']['token']
        sids.add(jwt.decode(token, options={'verify_signature': False})['sid'])
        return token

    async def business(token):
        return await client.get(gateway_url + '/api/agent/conversations', headers={'Authorization':'Bearer ' + token})

    await db.connect()
    try:
        auth_process = await start('auth', 'auth-service/target/easyjob-auth-0.0.1-SNAPSHOT.jar')
        gateway_process = await start('gateway', 'gateway/target/easyjob-gateway-0.0.1-SNAPSHOT.jar')
        await asyncio.gather(ready(auth_url, auth_process), ready(gateway_url, gateway_process))
        print('Isolated Auth and Gateway ready.', flush=True)
        email, code, password = 'auth-smoke-' + secrets.token_hex(5) + '@example.invalid', '123456', 'Auth-test-' + secrets.token_hex(12)
        await redis.set('auth:v2:code:login:' + hashlib.sha256(email.encode()).hexdigest(), hashlib.sha256((email + ':' + code).encode()).hexdigest(), ex=600)
        response = await client.post(auth_url + '/api/auth/register', json={'email':email,'code':code,'password':password,'nickName':'auth-'+secrets.token_hex(5)})
        expect('isolated_auth_registration', response.status_code == 200)
        uid = int(response.json()['data']['userId'])
        old = remember(response)
        count = proxy.calls.get('/internal/auth/session/check', 0)
        expect('isolated_gateway_blog_agent_chain', (await business(old)).status_code == 200)
        expect('one_authoritative_check_per_business_request', proxy.calls.get('/internal/auth/session/check', 0) - count == 1)
        proxy.failed.update(('session','api','jwks'))
        expect('auth_unavailable_rejects_protected_request', (await business(old)).status_code == 503)
        for _ in range(11):
            await client.get(gateway_url + '/api/auth/jwks')
        expect('auth_outage_does_not_break_anonymous_articles', (await client.get(gateway_url + '/api/article/list')).status_code == 200)
        proxy.failed.clear()
        expect('business_recovers_after_auth_dependency_recovers', (await business(old)).status_code == 200)
        proxy.failed.add('jwks')
        expect('cached_key_survives_jwks_outage', (await business(old)).status_code == 200)
        # New key ID forces a JWKS fetch. Outage must be 503, not a logout-inducing 401.
        key = jwt.algorithms.RSAAlgorithm.from_jwk((work / 'keys/auth-private.json').read_text())
        claims = jwt.decode(old, options={'verify_signature': False})
        unknown = jwt.encode(claims, key, algorithm='RS256', headers={'kid':'unpublished-test-key'})
        await asyncio.sleep(2.2)
        expect('uncached_key_dependency_failure_is_503', (await business(unknown)).status_code == 503)
        proxy.failed.clear()
        rotate('prepare', work / 'keys')
        jwks = (await client.get(auth_url + '/api/auth/jwks')).json()['keys']
        expect('next_public_key_published_before_activation', len(jwks) == 2)
        rotate('activate', work / 'keys')
        await stop(auth_process)
        auth_process = await start('auth', 'auth-service/target/easyjob-auth-0.0.1-SNAPSHOT.jar')
        await ready(auth_url, auth_process)
        expect('old_access_survives_auth_restart_and_rotation', (await business(old)).status_code == 200)
        # A new browser/device preserves the original session. Reusing the same
        # cookie would intentionally revoke it during the new login.
        async with httpx.AsyncClient(timeout=10, trust_env=False) as another_device:
            response = await another_device.post(auth_url + '/api/auth/login', json={'email':email,'password':password})
        expect('login_after_signing_key_rotation', response.status_code == 200)
        new = remember(response)
        expect('rotation_changes_signing_key', jwt.get_unverified_header(old)['kid'] != jwt.get_unverified_header(new)['kid'])
        expect('original_device_survives_new_device_login', (await business(old)).status_code == 200)
        expect('gateway_refreshes_jwks_for_new_signing_key', (await business(new)).status_code == 200)
        print('Auth/JWKS outage and live signing-key rotation checks passed.', flush=True)
        auth_redis.interrupt()
        expect('auth_redis_failure_is_503', (await business(new)).status_code == 503)
        expect('auth_redis_failure_preserves_anonymous_reading', (await client.get(gateway_url + '/api/article/list')).status_code == 200)
        auth_redis.enabled = True
        await ready(auth_url, auth_process, timeout=35)
        expect('session_checks_recover_after_auth_redis', (await business(new)).status_code == 200)
        gateway_redis.interrupt()
        expect('gateway_limiter_redis_failure_rejects_request', (await business(new)).status_code == 503)
        gateway_redis.enabled = True
        await ready(gateway_url, gateway_process, timeout=35)
        expect('gateway_recovers_after_limiter_redis', (await business(new)).status_code == 200)
        report = {'started_at':started, 'completed_at':datetime.now(timezone.utc).isoformat(), 'passed':len(checks), 'checks':checks, 'isolated_ports':True, 'model_calls':0, 'emails_sent':0}
        (ROOT / 'temp/unified-auth-resilience-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'passed':len(checks),'model_calls':0,'emails_sent':0}), flush=True)
    finally:
        for process in processes:
            await stop(process)
        for stream in streams:
            stream.close()
        for sid in sids:
            await redis.delete('auth:v2:session:' + sid)
        if uid:
            await redis.delete('auth:v2:devices:' + str(uid))
            await db.execute('DELETE FROM auth_outbox WHERE user_id=:uid', {'uid':uid})
            await db.execute('DELETE FROM auth_audit WHERE target_id=:uid OR actor_id=:uid', {'uid':uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid', {'uid':uid})
        await db.disconnect()
        await redis.aclose()
        await client.aclose()
        await proxy.close()
        await auth_redis.close()
        await gateway_redis.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Isolated resilience check failed:', type(error).__name__, str(error) if isinstance(error, AssertionError) else 'inspect ignored test logs')
        raise SystemExit(1)
