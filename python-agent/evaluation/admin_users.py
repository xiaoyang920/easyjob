"""Opt-in local admin-edit HTTP/SQL integration probe using disposable users only.

python -m evaluation.admin_users
--keep-ui keeps the marked fixtures for browser QA; --cleanup removes those exact IDs.
No LLM calls. Never runs against a remote database or Java service.
"""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
import httpx
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'temp' / 'admin-user-fixtures.json'
PASSWORD = 'Local-admin-edit-probe-2026!'


async def cleanup(fixtures):
    # Match both generated identity and reserved invalid-domain email before any delete.
    for user in fixtures:
        uid = int(user['id'])
        if await db.fetch_val('SELECT email FROM user_info WHERE user_id=:id', {'id': uid}) != user['email']:
            raise RuntimeError('Fixture identity changed; refusing cleanup')
        await db.execute("DELETE FROM admin_operation_log WHERE target_type='user' AND target_id=:id", {'id': uid})
        await db.execute('DELETE FROM user_reading_progress WHERE user_id=:id', {'id': uid})
        await db.execute('DELETE FROM user_info WHERE user_id=:id AND email=:email', {'id': uid, 'email': user['email']})


async def run(args):
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}, 'Local database required'
    assert urlparse(args.base).hostname in {'localhost', '127.0.0.1', '::1'}, 'Local Java required'
    await db.connect()
    if args.cleanup:
        try:
            await cleanup(json.loads(MANIFEST.read_text(encoding='utf-8')))
            MANIFEST.unlink()
            print('Disposable users removed; original accounts preserved.')
        finally:
            await db.disconnect()
        return
    if MANIFEST.exists():
        await db.disconnect()
        raise RuntimeError('Existing probe fixtures; run --cleanup first')
    marker = uuid4().hex[:12]
    ids = SnowflakeGenerator(worker_id=27)
    fixtures = [{'id': str(ids.next_id()), 'email': f'admin-edit-{kind}-{marker}@example.invalid', 'name': name, 'role': role}
                for kind, name, role in [('admin', '管理测试账号', 2), ('user', '编辑测试账号', 1)]]
    created, checks = [], []
    async with httpx.AsyncClient(base_url=args.base, timeout=15, trust_env=False) as client:
        async def call(method, path, token=None, body=None, code=200):
            response = await client.request(method, path, headers={'Authorization': f'Bearer {token}'} if token else {}, json=body)
            result = response.json()
            assert result.get('code') == code, (method, path, response.status_code, result.get('code'), result.get('message'))
            return result.get('data')
        async def login(user):
            # Each actor represents an independent browser; logging in must not revoke another fixture's cookie.
            client.cookies.clear()
            result = await call('POST', '/api/auth/login', body={'email': user['email'], 'password': PASSWORD})
            return result['token']
        async def detail():
            return await call('GET', f'/api/admin/users/{target}', token)
        def edit(current, **changes):
            profile = {key: current.get(key) for key in ('nickName', 'personIntroduction', 'role', 'status')}
            return {'expectedProfile': profile, **profile, 'reason': '隔离测试：管理员编辑回归', **changes}
        try:
            for user in fixtures:
                await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                    VALUES(:id,:name,:email,:password,NULL,NOW(),2,1,0,0,1,:role,0,0,0)""", {**user, 'id': int(user['id']), 'password': PASSWORD})
                created.append(user)
            token, normal = await login(fixtures[0]), await login(fixtures[1])
            target = fixtures[1]['id']
            for method, path, body in [('GET', '/api/admin/users', None), ('GET', f'/api/admin/users/{target}', None), ('PUT', f'/api/admin/users/{target}', {})]:
                await call(method, path, normal, body, 403)
            checks.append('ordinary user cannot list/read/edit admin data')
            current = await detail()
            assert not {'password', 'email', 'authVersion', 'auth_version'} & current.keys()
            checks.append('detail field allowlist omits credentials and private contact')
            await call('PUT', f'/api/admin/users/{target}', token, edit(current, nickName='改名测试', personIntroduction='新的简介'))
            changed = await detail()
            assert changed['nickName'] == '改名测试' and changed['personIntroduction'] == '新的简介'
            await call('GET', '/api/user/space/' + target, normal)
            await call('PUT', f'/api/admin/users/{target}', token, edit(current), 409)
            checks.append('profile edit persists; concurrent stale edit is rejected; login remains valid')
            await call('PUT', f'/api/admin/users/{target}', token, edit(changed, role=9), 400)
            await call('PUT', f'/api/admin/users/{target}', token, edit(changed, reason=''), 400)
            await call('PUT', f'/api/admin/users/{target}', token, edit(changed, personIntroduction='x' * 201), 400)
            checks.append('invalid role/reason/oversized biography rejected')
            await call('PUT', f'/api/admin/users/{target}', token, edit(changed, readingSeconds=3600, expectedReadingMillis=changed['readingMillis']))
            progress = await detail()
            expected_level = max(r['level'] for r in progress['rules'] if r['minSeconds'] <= 3600)
            assert progress['readingSeconds'] == 3600 and progress['readingLevel'] == expected_level
            await call('PUT', f'/api/admin/users/{target}', token, edit(progress, readingSeconds=0, expectedReadingMillis='0'), 409)
            await call('PUT', f'/api/admin/users/{target}', token, edit(progress, readingSeconds=0, expectedReadingMillis=progress['readingMillis']))
            assert (await detail())['readingLevel'] == 0
            checks.append('growth correction derives levels in both directions; stale duration cannot overwrite')
            await call('PUT', f'/api/admin/users/{target}', token, edit(await detail(), role=2))
            await call('GET', '/api/admin/me', normal, code=401)
            normal = await login(fixtures[1])
            await call('GET', '/api/admin/me', normal)
            checks.append('promotion revokes old login; fresh login receives administrator access')
            await call('PUT', f'/api/admin/users/{target}', token, edit(await detail(), status=0))
            await call('GET', '/api/admin/me', normal, code=401)
            await call('POST', '/api/auth/login', body={'email': fixtures[1]['email'], 'password': PASSWORD}, code=401)
            await call('PUT', f'/api/admin/users/{target}', token, edit(await detail(), status=1, role=1))
            await call('GET', '/api/admin/me', normal, code=401)
            normal = await login(fixtures[1])
            await call('GET', '/api/admin/me', normal, code=403)
            checks.append('disable blocks login; reenable does not revive revoked sessions; demotion removes admin access')
            own = await call('GET', '/api/admin/users/' + fixtures[0]['id'], token)
            await call('PUT', '/api/admin/users/' + fixtures[0]['id'], token, edit(own, role=1), 409)
            await call('PUT', '/api/admin/users/' + fixtures[0]['id'], token, edit(own, status=0), 409)
            checks.append('administrator cannot demote or disable their own account')
            audit = await db.fetch_all("SELECT reason,details_json FROM admin_operation_log WHERE target_type='user' AND target_id=:id ORDER BY id", {'id': int(target)})
            assert len(audit) == 6
            assert all(r['reason'] and json.loads(r['details_json'])['after']['profile'] for r in audit)
            checks.append('six successful changes have complete transactional audit; rejected writes have none')
            output = ROOT / 'temp' / 'admin-user-results.json'
            output.write_text(json.dumps({'passed': len(checks), 'checks': checks, 'scope': 'isolated local HTTP + real MySQL/Redis, no real user modified'}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': len(checks), 'report': str(output)}, ensure_ascii=False))
            if args.keep_ui:
                MANIFEST.write_text(json.dumps(created, ensure_ascii=False), encoding='utf-8')
                print('UI fixture email: ' + fixtures[0]['email'])
        finally:
            if not args.keep_ui or not MANIFEST.exists():
                await cleanup(created)
            await db.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8080')
    parser.add_argument('--keep-ui', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    asyncio.run(run(parser.parse_args()))
