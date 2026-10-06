"""Seed/remove authored examples in the local app using a dedicated test author."""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time

import httpx
import yaml
from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient, ARTICLE_CHUNK_VERSION
from evaluation.run import read_jsonl

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / 'datasets'
LOCAL = ROOT / 'logs/evaluation/sample-corpus-v1'
AUTHOR = 'RAG评测样例'
EMAIL = 'rag-eval-v1@sample.invalid'


def local_token(uid):
    # Only a loopback endpoint is used; the token and local secret are never logged.
    def merge(base, override):
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict): merge(base[key], value)
            else: base[key] = value
    config = yaml.safe_load((ROOT / 'src/main/resources/application.yml').read_text(encoding='utf-8'))
    active = config.get('spring', {}).get('profiles', {}).get('active', 'dev')
    profile = ROOT / f'src/main/resources/application-{active}.yml'
    if profile.exists(): merge(config, yaml.safe_load(profile.read_text(encoding='utf-8')) or {})
    merge(config, yaml.safe_load((ROOT / 'temp/application-runtime.yml').read_text(encoding='utf-8')))
    key = config['easyjob']['jwt']['secret-key']
    if not isinstance(key, str) or key.startswith('${'): raise ValueError('Unresolved local JWT config')
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=')
    body = enc(json.dumps({'userId': uid, 'sub': str(uid), 'iat': int(time.time()), 'exp': int(time.time()) + 3600}).encode())
    content = enc(b'{"alg":"HS512","typ":"JWT"}') + b'.' + body
    return (content + b'.' + enc(hmac.new(key.encode(), content, hashlib.sha512).digest())).decode()


def bind_cases(cases, mapping):
    bound = []
    for case in cases:
        bound.append({**case, 'relevance': {mapping[key]['article_id']: grade for key, grade in case['relevance'].items()},
                      'filters': {'author_name': AUTHOR},
                      'label_basis': [{**note, 'document': mapping[note['document']]['article_id']}
                                      for note in case.get('label_basis', [])]})
    return bound


async def seed(client, uid, articles):
    category = await db.fetch_val('SELECT category_id FROM article_info WHERE category_id IS NOT NULL AND deleted=0 LIMIT 1')
    if category is None: raise ValueError('No existing category ID available')
    mapping = {}
    LOCAL.mkdir(parents=True, exist_ok=True)
    for sample in articles:
        fingerprint = hashlib.sha256(sample['content'].encode()).hexdigest()
        existing = await db.fetch_all('SELECT article_id,content,status FROM article_info WHERE user_id=:uid AND title=:title AND deleted=0',
                                     {'uid': uid, 'title': sample['title']})
        if len(existing) > 1: raise ValueError('Duplicate sample titles; manual review needed')
        if existing:
            row = existing[0]
            if row['content'] != sample['content'] or row['status'] != 1:
                raise ValueError('Sample changed; refusing to overwrite user edits')
            aid = str(row['article_id'])
        else:
            result = (await client.post('/article/create', json={
                'title': sample['title'], 'content': sample['content'], 'summary': sample['summary'],
                'categoryId': str(category), 'contentType': sample['content_type'], 'isOriginal': 1,
                'status': 1, 'tagNames': []})).json()
            if result.get('code') != 200: raise ValueError('Local sample publish failed: ' + str(result.get('code')))
            aid = str(result['data']['articleId'])
        mapping[sample['id']] = {'article_id': aid, 'source_hash': fingerprint}
        (LOCAL / 'manifest.json').write_text(json.dumps({'author_id': uid, 'author_name': AUTHOR, 'samples': mapping,
            'annotation_source': 'synthetic_authored'}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{sample['id']} -> {aid}", flush=True)
    cases = bind_cases(read_jsonl(DATA / 'rag.samples.cases.jsonl'), mapping)
    (LOCAL / 'cases.jsonl').write_text(''.join(json.dumps(case, ensure_ascii=False) + '\n' for case in cases), encoding='utf-8')
    es = BaseEsClient()
    try:
        expected = {item['article_id']: item['source_hash'] for item in mapping.values()}
        deadline = time.monotonic() + 300
        last_ready = -1
        while True:
            response = await es.client.search(index='article_vectors', size=1000, source=['article_id', 'source_hash'],
                query={'bool': {'filter': [{'term': {'user_id': uid}}, {'term': {'chunker_version': ARTICLE_CHUNK_VERSION}}]}})
            ready = {str(hit['_source']['article_id']) for hit in response['hits']['hits']
                     if expected.get(str(hit['_source']['article_id'])) == hit['_source'].get('source_hash')}
            if len(ready) != last_ready:
                print(f'Indexed current articles: {len(ready)}/{len(expected)}', flush=True); last_ready = len(ready)
            if len(ready) == len(expected): break
            if time.monotonic() >= deadline: raise TimeoutError('Sample index not ready; rerun seed to check readiness')
            await asyncio.sleep(3)
    finally:
        await es.client.close()
    count = await db.fetch_val('SELECT article_count FROM user_info WHERE user_id=:uid', {'uid': uid})
    actual = await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE user_id=:uid AND status=1 AND deleted=0', {'uid': uid})
    if count != actual: raise ValueError('Sample author count mismatch')
    print(f'Ready: {len(articles)} articles, {len(cases)} synthetic labelled cases. Dataset: {LOCAL / "cases.jsonl"}')


async def cleanup(client, uid):
    manifest = json.loads((LOCAL / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['author_id'] != uid: raise ValueError('Sample owner mismatch')
    # Validate every target before starting deletion; only explicit manifest IDs are touched.
    targets = []
    for sample in manifest['samples'].values():
        row = await db.fetch_one('SELECT user_id,content FROM article_info WHERE article_id=:aid', {'aid': int(sample['article_id'])})
        if row is None: continue
        if row['user_id'] != uid or hashlib.sha256(row['content'].encode()).hexdigest() != sample['source_hash']:
            raise ValueError('Sample modified or ownership changed; cleanup stopped')
        targets.append(sample['article_id'])
    for aid in targets:
        result = (await client.delete('/article/' + aid)).json()
        if result.get('code') != 200: raise ValueError('Sample cleanup failed')
    print(f'Removed {len(targets)} unmodified sample articles; retained the original manifest.')


async def main(action):
    articles = read_jsonl(DATA / 'rag.samples.articles.jsonl')
    await db.connect()
    try:
        row = await db.fetch_one('SELECT user_id,email,person_introduction FROM user_info WHERE nick_name=:name', {'name': AUTHOR})
        intro = '合成 RAG 评测语料专用账号；非真实用户内容。'
        if row and (row['email'] != EMAIL or row['person_introduction'] != intro):
            raise ValueError('Reserved sample author name belongs to another account')
        if not row:
            if action == 'cleanup': raise ValueError('No sample author exists')
            uid = int(time.time() * 1000) << 10
            # An opaque random local-only credential is discarded immediately.
            await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
                status,total_coin_count,current_coin_count,theme,role,article_count,follower_count,following_count)
                VALUES(:uid,:name,:email,:password,:intro,NOW(),2,0,0,1,1,0,0,0)''',
                {'uid': uid, 'name': AUTHOR, 'email': EMAIL, 'password': secrets.token_urlsafe(60), 'intro': intro})
        else:
            uid = int(row['user_id'])
        async with httpx.AsyncClient(base_url='http://127.0.0.1:3000/api', timeout=30,
                                   headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
            if action == 'seed': await seed(client, uid, articles)
            else: await cleanup(client, uid)
    finally:
        await db.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('seed', 'cleanup'))
    asyncio.run(main(parser.parse_args().action))
