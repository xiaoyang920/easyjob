"""Loopback-only Chinese analysis verification, additive migration and synonym reload."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import struct
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'src/main/resources/elasticsearch'
FIELDS = {'article': ['title', 'summary', 'content'], 'article_vectors': ['title', 'chunk_content', 'section_path']}


class Es:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.query or parsed.path not in ('', '/'):
            raise ValueError('This maintenance tool only accepts a loopback ES URL')
        self.url = url.rstrip('/')
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.major = int(self.call('GET', '/')['version']['number'].split('.')[0])

    def call(self, method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(self.url+path, data=data, method=method,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.http.open(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            failure = json.loads(error.read().decode())
            detail = failure.get('error', {})
            reason = detail.get('reason', '') if isinstance(detail, dict) else str(detail)
            raise RuntimeError(f'ES {error.code}: {reason[:240]}') from None


def analysis_settings():
    return json.loads((ASSETS/'chinese-analysis.json').read_text(encoding='utf-8'))


def additions(properties, fields):
    result = {}
    for field in fields:
        existing = properties.get(field, {'type': 'text', 'analyzer': 'ik_smart'})
        if existing.get('type') != 'text':
            raise ValueError(f'{field} must be a text field')
        result[field] = {'type': 'text', 'fields': {'zh': {'type': 'text',
            'analyzer': 'easyjob_zh_index', 'search_analyzer': 'easyjob_zh_search'}}}
        if 'analyzer' in existing:
            result[field]['analyzer'] = existing['analyzer']
    return {'properties': result}


def asset_hashes():
    return {name: hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()
        for name in ['chinese-analysis.json', 'easyjob-technical.dic', 'easyjob-synonyms.txt']}


def fingerprint(es, index):
    source = {'exclude_vectors': False} if es.major >= 9 else True
    response = es.call('POST', f'/{index}/_search?scroll=2m', {'size': 100, '_source': source, 'sort': ['_doc']})
    scroll = None
    hashes, vectors = [], 0
    try:
        while True:
            scroll = response.get('_scroll_id', scroll)
            hits = response['hits']['hits']
            if not hits:
                break
            for hit in hits:
                document = hit['_source']
                vector = document.get('content_vector')
                if vector is not None:
                    if not isinstance(vector, list) or not all(type(v) in (float, int) and math.isfinite(v) for v in vector):
                        raise ValueError('Invalid stored vector')
                    # KNN indexes float32; rehydration in ES9 can round original doubles.
                    document['content_vector'] = [struct.unpack('f', struct.pack('f', value))[0] for value in vector]
                    vectors += 1
                payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                hashes.append((hit['_id'], hashlib.sha256(payload.encode()).hexdigest()))
            response = es.call('POST', '/_search/scroll', {'scroll': '2m', 'scroll_id': scroll})
    finally:
        if scroll:
            es.call('DELETE', '/_search/scroll', {'scroll_id': [scroll]})
    return {'documents': len(hashes), 'vectors': vectors,
        'source_sha256_float32_vectors': hashlib.sha256(json.dumps(sorted(hashes)).encode()).hexdigest()}


def validate_profile(es):
    probe = 'easyjob_zh_probe_'+uuid4().hex
    created = False
    try:
        es.call('PUT', '/'+probe, {'settings': {**analysis_settings(), 'number_of_shards': 1, 'number_of_replicas': 0}})
        created = True
        checks = {}
        for word in ['缓存穿透', '缓存击穿', '缓存雪崩', '分布式事务', '检索增强生成', '倒排索引']:
            result = es.call('POST', f'/{probe}/_analyze', {'analyzer': 'easyjob_zh_search', 'text': word})
            checks[word] = word in [token['token'] for token in result['tokens']]
        for word, equivalent in [('ES', 'elasticsearch'), ('Spring Boot', 'springboot'), ('RAG', '检索增强生成')]:
            result = es.call('POST', f'/{probe}/_analyze', {'analyzer': 'easyjob_zh_search', 'text': word})
            checks[word] = equivalent in [token['token'] for token in result['tokens']]
        if not all(checks.values()):
            raise ValueError('IK dictionary/synonym checks failed: '+', '.join(k for k,v in checks.items() if not v))
        return checks
    finally:
        if created:
            es.call('DELETE', '/'+probe)


def apply_index(es, index, report, *, test_fields=None):
    if index not in FIELDS and not (test_fields and index.startswith('easyjob_zh_migration_test_')):
        raise ValueError('Only the two project search indexes can be migrated')
    metadata = es.call('GET', '/'+index)[index]
    if metadata['settings']['index'].get('blocks', {}).get('write') == 'true':
        raise ValueError('Index is already write-blocked; refusing to override operator state')
    original_mapping = metadata['mappings']
    fields = test_fields if test_fields is not None else FIELDS[index]
    new_mapping = additions(original_mapping.get('properties', {}), fields)
    if original_mapping.get('_meta', {}).get('easyjob_chinese_analysis') == asset_hashes() and all(
            original_mapping.get('properties', {}).get(field, {}).get('fields', {}).get('zh', {}).get('search_analyzer') == 'easyjob_zh_search'
            for field in fields):
        report['indexes'].append({'index': index, 'state': 'already verified', 'before': fingerprint(es, index)})
        return
    backup = f'easyjob_zh_backup_{index}_'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'_'+uuid4().hex[:8]
    row = {'index': index, 'backup': backup, 'state': 'started'}
    report['indexes'].append(row)
    row['before'] = fingerprint(es, index)
    blocked = False
    try:
        es.call('PUT', f'/{index}/_block/write');blocked = True
        es.call('POST', f'/{index}/_clone/{backup}', {'settings': {'number_of_replicas': 0}})
        health = es.call('GET', f'/_cluster/health/{backup}?wait_for_status=yellow&timeout=60s')
        if health.get('timed_out') or health.get('status') not in ('yellow', 'green'):
            raise ValueError('Backup shards are not ready')
        if fingerprint(es, backup) != row['before']:
            raise ValueError('Backup source/vector fingerprint mismatch')
    finally:
        if blocked:
            es.call('PUT', f'/{index}/_settings', {'index.blocks.write': False})
    closed = False
    try:
        es.call('POST', f'/{index}/_close');closed = True
        es.call('PUT', f'/{index}/_settings', analysis_settings())
    finally:
        if closed:
            es.call('POST', f'/{index}/_open')
    es.call('PUT', f'/{index}/_mapping', new_mapping)
    response = es.call('POST', f'/{index}/_update_by_query?refresh=true&conflicts=abort&requests_per_second=200', {'query': {'match_all': {}}})
    if response.get('timed_out') or response.get('failures') or response.get('version_conflicts'):
        raise ValueError('Backfill incomplete; original fields and backup preserved')
    row['updated'] = response.get('updated', 0)
    row['after'] = fingerprint(es, index)
    if row['before'] != row['after']:
        raise ValueError('Original document/vector fingerprint changed')
    es.call('PUT', f'/{index}/_mapping', {'_meta': {**original_mapping.get('_meta', {}), 'easyjob_chinese_analysis': asset_hashes()}})
    row['state'] = 'verified'


def verify_search(es):
    index = 'easyjob_zh_search_test_'+uuid4().hex
    created = False
    documents = [
        ('es', 'Elasticsearch 倒排索引原理'), ('spring', 'SpringBoot 自动配置与依赖注入'),
        ('rag', '检索增强生成与混合检索'), ('penetration', 'Redis 缓存穿透与布隆过滤器'),
        ('breakdown', 'Redis 缓存击穿与互斥锁'), ('avalanche', 'Redis 缓存雪崩与过期时间'),
        ('llm', '大语言模型与工具调用'), ('k8s', 'Kubernetes 服务发现'),
        ('ws', 'WebSocket 实时聊天'), ('transaction', '分布式事务与最终一致性')]
    queries = [('ES','es'), ('elasticsearch','es'), ('Spring Boot','spring'), ('springboot','spring'),
        ('RAG','rag'), ('检索增强生成','rag'), ('缓存穿透','penetration'), ('缓存击穿','breakdown'),
        ('缓存雪崩','avalanche'), ('LLM','llm'), ('k8s','k8s'), ('WS','ws'), ('分布式事务','transaction')]
    try:
        mapping = additions({'title': {'type': 'text', 'analyzer': 'ik_smart'}}, ['title'])
        es.call('PUT', '/'+index, {'settings': {**analysis_settings(), 'number_of_shards': 1, 'number_of_replicas': 0}, 'mappings': mapping})
        created = True
        for identity, title in documents:
            es.call('PUT', f'/{index}/_doc/{identity}', {'title': title})
        es.call('POST', f'/{index}/_refresh')
        results = []
        for query, expected in queries:
            response = es.call('POST', f'/{index}/_search', {'query': {'match': {'title.zh': query}}, 'size': 5,
                'highlight': {'fields': {'title.zh': {}, 'title': {}}}})
            ids = [hit['_id'] for hit in response['hits']['hits']]
            highlighted = bool(response['hits']['hits'] and response['hits']['hits'][0].get('highlight', {}).get('title.zh'))
            results.append({'query': query, 'expected': expected, 'hits': ids, 'highlighted': highlighted,
                'passed': bool(ids) and ids[0] == expected and highlighted})
        # Different cache failure modes must never be treated as synonyms.
        for row in results:
            if row['expected'] in ('penetration', 'breakdown', 'avalanche'):
                row['passed'] = row['passed'] and row['hits'] == [row['expected']]
        return results
    finally:
        if created:
            es.call('DELETE', '/'+index)


def verify_migration(es):
    """Exercise old-index migration with an isolated corpus, including stored vectors."""
    index = 'easyjob_zh_migration_test_'+uuid4().hex
    report = {'indexes': []}
    created = False
    try:
        es.call('PUT', '/'+index, {'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
            'mappings': {'_meta': {'fixture': True}, 'properties': {
                'title': {'type': 'text', 'analyzer': 'ik_smart'},
                'content_vector': {'type': 'dense_vector', 'dims': 3, 'similarity': 'cosine'}}}})
        created = True
        for identity, title in [('es', 'Elasticsearch 倒排索引'), ('rag', '检索增强生成')]:
            es.call('PUT', f'/{index}/_doc/{identity}', {'title': title,
                'chunk_id': identity, 'source_hash': 'unchanged', 'content_vector': [0.123456789, 0.2, 0.3]})
        es.call('POST', f'/{index}/_refresh')
        apply_index(es, index, report, test_fields=['title'])
        result = es.call('POST', f'/{index}/_search', {'query': {'match': {'title.zh': 'RAG'}}})
        if [hit['_id'] for hit in result['hits']['hits']] != ['rag']:
            raise ValueError('Migrated old documents do not match query synonyms')
        mapping = es.call('GET', f'/{index}/_mapping')[index]['mappings']
        if mapping['_meta'].get('fixture') is not True:
            raise ValueError('Original mapping metadata was lost')
        return report['indexes'][0]
    finally:
        if created:
            es.call('DELETE', '/'+index)
        # Only backups created for this owned disposable fixture may be removed here.
        for row in report['indexes']:
            backup = row.get('backup')
            if backup and backup.startswith('easyjob_zh_backup_'+index+'_'):
                available = es.call('GET', '/_cat/indices?format=json')
                if any(item['index'] == backup for item in available):
                    es.call('DELETE', '/'+backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'plan', 'apply', 'reload'])
    parser.add_argument('--url', default='http://127.0.0.1:9200')
    parser.add_argument('--output', default=str(ROOT/'logs/chinese-search.json'))
    args = parser.parse_args()
    es = Es(args.url)
    report = {'action': args.action, 'asset_hashes': asset_hashes(), 'indexes': [], 'embedding_calls': 0}
    output = Path(args.output);output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.action in ('verify', 'apply'):
            report['analyze_checks'] = validate_profile(es)
            report['search_checks'] = verify_search(es)
            if not all(row['passed'] for row in report['search_checks']):
                raise ValueError('Chinese retrieval checks failed')
            report['migration_check'] = verify_migration(es)
        if args.action in ('plan', 'apply'):
            if args.action == 'apply':
                for port in (8080, 8000):
                    with socket.socket() as connection:
                        connection.settimeout(.3)
                        if connection.connect_ex(('127.0.0.1', port)) == 0:
                            raise ValueError('Stop project Java/Python writers before this maintenance migration')
            indexes = es.call('GET', '/_cat/indices?format=json')
            available = {row['index'] for row in indexes}
            for index in FIELDS:
                if index not in available:
                    report['indexes'].append({'index': index, 'state': 'absent; fresh startup will create the new mapping'})
                elif args.action == 'apply':
                    apply_index(es, index, report)
                else:
                    report['indexes'].append({'index': index, 'state': 'planned', 'before': fingerprint(es,index)})
        if args.action == 'reload':
            report['reload'] = es.call('POST', '/article,article_vectors/_reload_search_analyzers?ignore_unavailable=true')
            if report['reload'].get('_shards', {}).get('failed'):
                raise ValueError('Search analyzer reload failed')
            if not report['reload'].get('reload_details') or any(
                    'easyjob_zh_search' not in row.get('reloaded_analyzers', []) for row in report['reload']['reload_details']):
                raise ValueError('Chinese search analyzer is not installed on every requested index')
            es.call('POST', '/article,article_vectors/_cache/clear?request=true&ignore_unavailable=true')
        report['passed'] = True
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__, error=str(error)[:300])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(not report['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
