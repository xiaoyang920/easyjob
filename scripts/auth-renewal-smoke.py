"""Real loopback login/expiry/refresh/revoke checks using one disposable user."""
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
import time

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.utils.snowflake import snowflake
from evaluation.local_samples import local_token


def payload(token):
    return json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))


def expired(token):
    config = yaml.safe_load((ROOT / 'src/main/resources/application.yml').read_text(encoding='utf-8'))
    runtime = yaml.safe_load((ROOT / 'temp/application-runtime.yml').read_text(encoding='utf-8'))
    key = runtime.get('easyjob', {}).get('jwt', {}).get('secret-key') or config['easyjob']['jwt']['secret-key']
    value = payload(token); value['exp'] = int(time.time()) - 60
    header = token.split('.')[0]
    body = base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()
    signed = (header + '.' + body).encode()
    signature = base64.urlsafe_b64encode(hmac.new(key.encode(), signed, hashlib.sha512).digest()).rstrip(b'=').decode()
    return header + '.' + body + '.' + signature


async def main():
    uid = snowflake.next_id()
    email = 'auth-test-' + secrets.token_hex(8) + '@sample.invalid'
    password = secrets.token_urlsafe(30)
    marker = '临时登录续签评测账号'
    checks = []
    await db.connect()
    client = httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=15)
    try:
        await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
            status,sex,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count)
            VALUES(:uid,:name,:email,:password,:marker,NOW(),1,2,0,0,0,1,1,0,0)""",
            {'uid': uid, 'name': '续签测试' + secrets.token_hex(4), 'email': email, 'password': password, 'marker': marker})

        async def refresh(token=None, headers=None):
            return await client.post('/auth/refresh', headers={
                'X-Auth-Refresh': '1', **({'Authorization': 'Bearer ' + token} if token else {}), **(headers or {})})

        async def protected(token):
            return await client.get('/agent/memory', headers={'Authorization': 'Bearer ' + token})

        login = await client.post('/auth/login', json={'email': email, 'password': password})
        assert login.json()['code'] == 200, 'login failed'
        token = login.json()['data']['token']
        cookie = login.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie and 'path=/api/auth' in cookie
        claims = payload(token)
        assert claims.get('sid') and claims['exp'] - claims['iat'] == 1800
        assert (await protected(token)).json()['code'] == 200
        checks.append('login_http_only_cookie_and_30_min_access_token')

        old = expired(token)
        assert (await protected(old)).status_code == 401
        renewed = await refresh(old)
        assert renewed.json()['code'] == 200
        token = renewed.json()['data']['token']
        assert (await protected(token)).json()['code'] == 200
        assert 'set-cookie' not in renewed.headers
        checks.append('expired_access_token_recovers_through_refresh_cookie')

        responses = await asyncio.gather(*[refresh(old) for _ in range(8)])
        assert all(r.json()['code'] == 200 for r in responses)
        assert {payload(r.json()['data']['token'])['sid'] for r in responses} == {claims['sid']}
        checks.append('parallel_refresh_requests_preserve_one_session')

        assert (await client.post('/auth/refresh')).json()['code'] == 403
        assert (await refresh(headers={'Sec-Fetch-Site': 'cross-site'})).json()['code'] == 403
        checks.append('refresh_rejects_missing_header_and_cross_site_request')

        assert (await client.post('/auth/logout', headers={'X-Auth-Refresh': '1'})).json()['code'] == 200
        assert (await protected(token)).status_code == 401
        assert (await refresh(token)).json()['code'] == 401
        checks.append('logout_revokes_access_token_and_refresh_session')

        legacy = local_token(uid)
        assert (await refresh(expired(legacy))).json()['code'] == 401
        migrated = await refresh(legacy)
        assert migrated.json()['code'] == 200 and 'set-cookie' in migrated.headers
        token = migrated.json()['data']['token']
        assert payload(token)['sid'] and (await protected(token)).json()['code'] == 200
        checks.append('valid_legacy_migrates_but_expired_legacy_cannot_renew')

        await db.execute('UPDATE user_info SET status=0 WHERE user_id=:uid', {'uid': uid})
        assert (await refresh(token)).json()['code'] == 401
        assert (await protected(token)).status_code == 401
        checks.append('disabled_account_invalidates_session_on_refresh')

        report = {'checks': checks, 'passed': len(checks), 'temporary_user_cleaned': False}
        print(f'Auth renewal: {len(checks)} live checks passed; no credentials logged.', flush=True)
    finally:
        try:
            await client.post('/auth/logout', headers={'X-Auth-Refresh': '1'})
            owner = await db.fetch_one('SELECT email,person_introduction FROM user_info WHERE user_id=:uid', {'uid': uid})
            if owner and owner['email'] == email and owner['person_introduction'] == marker:
                await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': email})
                if 'report' in locals():
                    report['temporary_user_cleaned'] = True
                    (ROOT / 'logs/auth-renewal-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            await client.aclose()
            await db.disconnect()


if __name__ == '__main__': asyncio.run(main())
