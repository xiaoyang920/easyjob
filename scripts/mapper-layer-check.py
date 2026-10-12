"""Local HTTP/MySQL checks for management Mapper XML, using disposable fixtures."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.utils.snowflake import SnowflakeGenerator
from evaluation.local_samples import local_token


async def main():
    assert db.url.hostname in {'localhost', '127.0.0.1', '::1'}, 'local fixtures only'
    ids = SnowflakeGenerator(worker_id=28)
    admin, author, article = [ids.next_id() for _ in range(3)]
    marker = 'mapper-' + uuid4().hex[:10]
    categories = []
    created = []
    report = {'checks': [], 'cleanup_complete': False,
              'scope': 'isolated local HTTP/MySQL; no LLM or embedding calls'}

    def check(name, passed):
        item = {'name': name, 'passed': bool(passed)}
        report['checks'].append(item)
        print(json.dumps(item), flush=True)
        assert passed, name

    async def call(client, method, path, expected=200, **kwargs):
        response = await client.request(method, path, **kwargs)
        body = response.json()
        code = response.status_code if response.status_code != 200 else body.get('code')
        assert code == expected, (path, code, expected, body.get('message'))
        return body.get('data')

    await db.connect()
    try:
        for uid in [admin, author]:
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,
                join_time,sex,status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,'LocalMapperQa2026!',:marker,NOW(),2,1,0,0,1,:role,0,0,0)''',
                {'uid': uid, 'name': 'Mapper' + str(uid)[-8:], 'email': f'{marker}-{uid}@sample.invalid',
                 'marker': marker, 'role': 2 if uid == admin else 1})
            created.append(uid)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', trust_env=False, timeout=20,
                                     headers={'Authorization': 'Bearer ' + local_token(admin)}) as manager:
            for source in ['business', 'evaluation', 'all']:
                metrics = await call(manager, 'GET', '/admin/agent-metrics', params={'days': 7, 'source': source})
                check('metrics_source_' + source, metrics['source'] == source and len(metrics['daily']) == 7
                      and metrics['sampledRuns'] <= 10000)
            await call(manager, 'GET', '/admin/agent-metrics', 400, params={'days': 8})
            check('metrics_reject_invalid_period', True)

            profile = await call(manager, 'GET', f'/admin/users/{author}')
            expected = {key: profile.get(key) for key in ['nickName', 'personIntroduction', 'role', 'status']}
            update = {'expectedProfile': expected, **expected, 'nickName': 'MapperUpdated',
                      'readingSeconds': 120, 'expectedReadingMillis': '0', 'reason': marker}
            await call(manager, 'PUT', f'/admin/users/{author}', json=update)
            latest = await call(manager, 'GET', f'/admin/users/{author}')
            check('profile_and_reading_correction_persist', latest['nickName'] == 'MapperUpdated'
                  and latest['readingMillis'] == '120000')
            await call(manager, 'PUT', f'/admin/users/{author}', 409, json=update)
            check('stale_profile_rejected', True)
            latest_profile = {key: latest.get(key) for key in expected}
            await call(manager, 'PUT', f'/admin/users/{author}', 409,
                       json={**update, **latest_profile, 'expectedProfile': latest_profile})
            check('stale_reading_correction_rejected', True)
            check('failed_updates_do_not_audit', await db.fetch_val(
                'SELECT COUNT(*) FROM admin_operation_log WHERE admin_user_id=:id AND action=\'user_update\'',
                {'id': admin}) == 1)

            async def category(suffix, parent=0):
                result = await call(manager, 'POST', '/admin/categories', json={
                    'categoryName': marker + suffix, 'parentId': parent, 'sortOrder': 0, 'description': marker})
                categories.append(int(result['categoryId']))
                return int(result['categoryId'])

            source = await category('-source')
            target = await category('-target')
            child = await category('-child', source)
            await call(manager, 'POST', '/admin/categories', 409,
                       json={'categoryName': marker + '-source', 'parentId': 0})
            check('duplicate_category_rejected', True)
            await call(manager, 'PUT', f'/admin/categories/{source}', 409, json={
                'expectedVersion': 0, 'categoryName': marker + '-source', 'sortOrder': 0,
                'description': marker, 'status': 0})
            check('enabled_child_prevents_parent_disable', True)
            await call(manager, 'PUT', f'/admin/categories/{child}', json={
                'expectedVersion': 0, 'categoryName': marker + '-child', 'sortOrder': 1,
                'description': marker, 'status': 0})
            await db.execute('''INSERT INTO article_info(article_id,user_id,title,summary,content,content_type,
                category_id,status,deleted,required_level,create_time,update_time)
                VALUES(:id,:uid,:title,'fixture','<p>private fixture</p>',1,:category,0,0,1,NOW(),NOW())''',
                {'id': article, 'uid': author, 'title': marker, 'category': source})
            await call(manager, 'PUT', f'/admin/categories/{source}', json={
                'expectedVersion': 0, 'categoryName': marker + '-renamed', 'sortOrder': 2,
                'description': marker, 'status': 1})
            await call(manager, 'POST', f'/admin/categories/{source}/migrate', 409,
                       json={'expectedVersion': 0, 'targetId': target, 'targetVersion': 0})
            check('stale_category_migration_rejected', True)
            moved = await call(manager, 'POST', f'/admin/categories/{source}/migrate', json={
                'expectedVersion': 1, 'targetId': target, 'targetVersion': 0})
            rows = await call(manager, 'GET', '/admin/categories')
            source_row = next(row for row in rows if row['categoryId'] == str(source))
            target_row = next(row for row in rows if row['categoryId'] == str(target))
            check('migration_moves_private_article_and_redirects_source', moved['articleCount'] == 1
                  and source_row['status'] == 0 and source_row['migratedTo'] == str(target)
                  and target_row['articleCount'] == 1 and target_row['version'] == '1'
                  and await db.fetch_val('SELECT category_id FROM article_info WHERE article_id=:id',
                                         {'id': article}) == target)
            check('private_migration_does_not_enqueue_public_index', await db.fetch_val(
                'SELECT COUNT(*) FROM article_index_outbox WHERE article_id=:id', {'id': article}) == 0)
            check('category_changes_audited', await db.fetch_val(
                'SELECT COUNT(*) FROM admin_operation_log WHERE admin_user_id=:id AND target_type=\'category\'',
                {'id': admin}) == 6)
    finally:
        await db.execute('DELETE FROM article_info WHERE article_id=:id AND user_id=:uid AND title=:marker',
                         {'id': article, 'uid': author, 'marker': marker})
        for category_id in reversed(categories):
            await db.execute('DELETE FROM category WHERE category_id=:id AND description=:marker',
                             {'id': category_id, 'marker': marker})
        for uid in created:
            email = f'{marker}-{uid}@sample.invalid'
            if await db.fetch_val('SELECT COUNT(*) FROM user_info WHERE user_id=:id AND email=:email',
                                  {'id': uid, 'email': email}) != 1:
                raise RuntimeError('fixture identity changed; refusing cleanup')
            await db.execute('DELETE FROM admin_operation_log WHERE admin_user_id=:id', {'id': uid})
            await db.execute('DELETE FROM user_reading_progress WHERE user_id=:id', {'id': uid})
            await db.execute('DELETE FROM user_info WHERE user_id=:id AND email=:email', {'id': uid, 'email': email})
        await db.disconnect()
        report['cleanup_complete'] = True
        output = ROOT / 'logs/evaluation' / f'mapper-layer-{datetime.now():%Y%m%d-%H%M%S}.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(output, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
