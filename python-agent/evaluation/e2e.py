"""Loopback-only full Agent benchmark, including approved/rejected draft persistence."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import re
import time
import importlib.metadata
from uuid import uuid4

import httpx

from evaluation.metrics import percentile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = Path(__file__).with_name('datasets') / 'e2e.cases.jsonl'


def score(trials, expected_count):
    identities = [(t.get('case_id', str(i)), t.get('repetition', 0)) for i, t in enumerate(trials)]
    if len(set(identities)) != len(identities) or len(trials) > expected_count:
        raise ValueError('重复或超出计划数量的实验记录')
    ok = [t for t in trials if t.get('contract_passed')]
    measured = [t for t in trials if (t.get('metrics') or {}).get('token_usage_complete')]
    reviewed = [t for t in trials if (t.get('review') or {}).get('assessor') == 'human']
    claim_total = sum(t['review'].get('total_claims', 0) for t in reviewed)
    supported = sum(t['review'].get('supported_claims', 0) for t in reviewed)
    return {'expected_trials': expected_count, 'recorded_trials': len(trials),
            'automatic_contract_passed': len(ok), 'automatic_contract_pass_rate': len(ok) / expected_count if expected_count else None,
            'total_latency_p95_ms_all_recorded': percentile([t['total_duration_ms'] for t in trials], 95),
            'total_latency_p95_ms_passed': percentile([t['total_duration_ms'] for t in ok], 95),
            'token_usage_measured_trials': len(measured), 'token_usage_missing_trials': expected_count - len(measured),
            'input_tokens_measured': sum(t['metrics']['input_tokens'] for t in measured),
            'output_tokens_measured': sum(t['metrics']['output_tokens'] for t in measured),
            'human_reviewed_trials': len(reviewed), 'human_review_pending': expected_count - len(reviewed),
            'human_task_completion_rate_reviewed_only': sum(t['review'].get('task_completed') is True for t in reviewed) / len(reviewed) if reviewed else None,
            'human_citation_support_rate_reviewed_only': supported / claim_total if claim_total else None}


def validate_review(review):
    if review.get('assessor') != 'human' or not isinstance(review.get('task_completed'), bool):
        raise ValueError('人工评审需标明 assessor=human 和 task_completed=true/false')
    supported, total = review.get('supported_claims'), review.get('total_claims')
    if type(supported) is not int or type(total) is not int or not 0 <= supported <= total:
        raise ValueError('引用支持数需满足 0 <= supported_claims <= total_claims')


def save_report(output, trials, manifest):
    summary = score(trials, manifest['expected_trials'])
    (output / 'summary.json').write_text(json.dumps({'manifest': manifest, **summary}, ensure_ascii=False, indent=2), encoding='utf-8')
    def percent(value): return '待人工标注' if value is None else f'{value:.1%}'
    report = f"""# 完整 Agent 评测

样本：{manifest['cases']} 条，计划 {manifest['expected_trials']} 次，已记录 {len(trials)} 次。失败、超时和缺失结果计入契约通过率分母。

| 指标 | 结果 |
|---|---:|
| 自动任务契约通过率 | {percent(summary['automatic_contract_pass_rate'])} |
| 整次请求 P95（全部已记录请求） | {summary['total_latency_p95_ms_all_recorded']} ms |
| 整次请求 P95（契约通过请求） | {summary['total_latency_p95_ms_passed']} ms |
| 完整 Token 计量覆盖 | {summary['token_usage_measured_trials']}/{manifest['expected_trials']} |
| 已计量输入 / 输出 Token | {summary['input_tokens_measured']} / {summary['output_tokens_measured']} |
| 人工任务完成率（仅已评审） | {percent(summary['human_task_completion_rate_reviewed_only'])} |
| 引用事实支持率（仅人工评审） | {percent(summary['human_citation_support_rate_reviewed_only'])} |

自动契约只验证可执行条件（响应、引用 ID、草稿审批和数据库保存状态），不能代替答案事实准确率。人工评审尚缺 {summary['human_review_pending']} 次。

耗时从 HTTP 请求开始到结果返回；草稿包括生成及审批恢复请求，审批由脚本立即给出，不包含人为等待。Token 为 Main、子代理及生成/修正模型调用之和；不含 embedding、rerank、图片预处理及后台事件提取。缺失 usage 不记成 0。LLM 次数按 LangChain 调用计数，未单独统计 SDK 内部 HTTP 重试。

predictions.jsonl 保留答案、引用和逐节点状态以供复核；reviews.template.jsonl 给出待标注记录。小样本本地验证不代表线上泛化准确率。
"""
    (output / 'report.md').write_text(report, encoding='utf-8')
    return summary


async def cleanup(uid, email, client):
    from app.clients.mysql_client import db
    from app.graph.builder import get_graph, close_graph
    from app.services.conversation import ConversationService
    from app.clients.es_client import BaseEsClient
    # Every delete is bound to this run's dedicated account, never a supplied user id.
    owner = await db.fetch_one('SELECT email,person_introduction FROM user_info WHERE user_id=:uid', {'uid': uid})
    if not owner or owner['email'] != email or owner['person_introduction'] != '临时端到端评测账号':
        raise RuntimeError('评测账号身份不一致，停止清理')
    articles = await db.fetch_all('SELECT article_id,status FROM article_info WHERE user_id=:uid', {'uid': uid})
    if any(r['status'] != 0 for r in articles):
        raise RuntimeError('发现非草稿文章，停止清理')
    for article in articles:
        response = await client.delete('/article/' + str(article['article_id']))
        response.raise_for_status()
        if response.json().get('code') != 200: raise RuntimeError('评测草稿清理失败')
    deadline = time.monotonic() + 30
    while await db.fetch_val("SELECT COUNT(*) FROM agent_background_job WHERE user_id=:uid AND status='running'", {'uid': uid}):
        if time.monotonic() > deadline: raise RuntimeError('后台任务尚未结束，请重试 cleanup')
        await asyncio.sleep(1)
    graph = await get_graph()
    conversations = ConversationService()
    es = BaseEsClient()
    try:
        for row in await db.fetch_all('SELECT run_id FROM agent_run WHERE user_id=:uid', {'uid': uid}):
            await graph.checkpointer.adelete_thread('run_' + row['run_id'])
        for row in await db.fetch_all('SELECT conversation_id FROM ai_conversation WHERE user_id=:uid', {'uid': uid}):
            await conversations.invalidate_cache(row['conversation_id'])
        for row in await db.fetch_all('SELECT memory_id FROM user_memory WHERE user_id=:uid', {'uid': uid}):
            await es.client.options(ignore_status=404).delete(index='user_memories', id=str(row['memory_id']))
        async with db.transaction():
            await db.execute('DELETE f FROM agent_stream_frame f JOIN agent_run r ON f.run_id=r.run_id WHERE r.user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM agent_execution_lease WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE e FROM agent_run_event e JOIN agent_run r ON e.run_id=r.run_id WHERE r.user_id=:uid', {'uid': uid})
            for table in ('user_memory_change', 'user_memory', 'user_profile', 'agent_background_job', 'agent_run'):
                await db.execute(f'DELETE FROM {table} WHERE user_id=:uid', {'uid': uid})
            await db.execute('DELETE m FROM ai_message m JOIN ai_conversation c ON m.conversation_id=c.conversation_id WHERE c.user_id=:uid', {'uid': uid})
            await db.execute('DELETE FROM ai_conversation WHERE user_id=:uid', {'uid': uid})
            for article in articles:
                aid = article['article_id']
                await db.execute('DELETE FROM article_tag_relation WHERE article_id=:aid', {'aid': aid})
                await db.execute('DELETE FROM article_index_outbox WHERE article_id=:aid', {'aid': aid})
                await db.execute('DELETE FROM article_info WHERE user_id=:uid AND article_id=:aid', {'uid': uid, 'aid': aid})
            await db.execute('DELETE FROM user_info WHERE user_id=:uid AND email=:email', {'uid': uid, 'email': email})
    finally:
        await es.client.close()
        await close_graph()
        await conversations._redis.client.aclose()


async def live(args, cases, output, manifest):
    from app.clients.mysql_client import db
    from app.utils.snowflake import snowflake
    from evaluation.local_samples import local_token
    await db.connect()
    trials = []
    try:
        if args.command == 'cleanup':
            fixture = json.loads((output / 'fixture.json').read_text(encoding='utf-8'))
            uid, email = fixture['uid'], fixture['email']
        else:
            uid, email = snowflake.next_id(), 'e2e-' + secrets.token_hex(8) + '@sample.invalid'
            password = secrets.token_urlsafe(30)
            await db.execute("""INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,
                join_time,sex,status,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
                VALUES(:uid,:name,:email,:password,'临时端到端评测账号',NOW(),2,1,0,0,0,1,1,0,0,'evaluation')""",
                {'uid': uid, 'email': email, 'name': 'Agent评测' + email[4:12], 'password': password})
            (output / 'fixture.json').write_text(json.dumps({'uid': uid, 'email': email, 'password': password}), encoding='utf-8')
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8080/api', timeout=args.timeout,
                                    headers={'Authorization': 'Bearer ' + local_token(uid)}) as client:
            if args.command == 'cleanup':
                await cleanup(uid, email, client); print('独立评测账号已清理', flush=True); return
            try:
                with (output / 'predictions.jsonl').open('w', encoding='utf-8') as file:
                    for repetition in range(args.repeats):
                        for case in cases:
                            trial = {'case_id': case['id'], 'repetition': repetition, 'query': case['query'], 'contract_passed': False}
                            started = time.perf_counter()
                            try:
                                response = await client.post('/agent/chat', json={'message': case['query'], 'requestId': str(uuid4())})
                                response.raise_for_status()
                                body = response.json()
                                if body.get('code') != 200: raise RuntimeError('chat_business_error')
                                answer = body['data']
                                cid, rid = answer['conversationId'], answer['runId']
                                payload = None
                                try:
                                    pending = json.loads(answer['reply'])
                                    if isinstance(pending, dict) and pending.get('interrupted'): payload = pending['payload']
                                except (ValueError, TypeError): pass
                                trial.update(conversation_id=cid, run_id=rid, interrupted=bool(payload))
                                if case.get('approval'):
                                    if not payload: raise RuntimeError('expected_draft_approval')
                                    count = await db.fetch_val('SELECT COUNT(*) FROM article_info WHERE user_id=:uid AND deleted=0', {'uid': uid})
                                    if count != len([t for t in trials if t.get('draft_saved')]): raise RuntimeError('draft_saved_before_approval')
                                    resumed = await client.post('/agent/chat/resume', json={'conversationId': cid, 'runId': rid,
                                        'draftHash': payload['draftHash'], 'action': case['approval']})
                                    resumed.raise_for_status()
                                    if resumed.json().get('code') != 200: raise RuntimeError('resume_business_error')
                                    answer = resumed.json()['data']
                                status = (await client.get('/agent/runs/' + rid)).json()['data']
                                trial.update(reply=answer['reply'], citations=answer.get('citations') or [], metrics=(status.get('result') or {}).get('metrics'), run_status=status['status'])
                                events = await db.fetch_all('SELECT node,status,duration_ms FROM agent_run_event WHERE run_id=:rid ORDER BY event_id', {'rid': rid})
                                trial['events'] = [dict(r._mapping) for r in events]
                                saved_id = answer.get('draftArticleId')
                                trial['draft_saved'] = bool(saved_id)
                                checks = {'succeeded': status['status'] == 'succeeded', 'nonempty_reply': bool(answer['reply'].strip())}
                                cited = set(re.findall(r'\[([a-z][a-z0-9_]*:(?:web)?\d+)\]', answer['reply']))
                                known = {c['id'] for c in trial['citations']}
                                checks['citation_ids_consistent'] = cited <= known
                                if case.get('required_citations'): checks['citations_present'] = bool(trial['citations'])
                                if case.get('required_nodes'): checks['required_nodes'] = all(any(node in e['node'] for e in trial['events']) for node in case['required_nodes'])
                                if case.get('required_terms'): checks['required_terms'] = all(term.casefold() in answer['reply'].casefold() for term in case['required_terms'])
                                if case.get('approval') == 'approve':
                                    row = await db.fetch_one('SELECT status,user_id FROM article_info WHERE article_id=:aid AND deleted=0', {'aid': int(saved_id or 0)})
                                    checks['approved_draft_persisted'] = bool(row and row['status'] == 0 and row['user_id'] == uid)
                                if case.get('approval') == 'reject': checks['rejected_not_saved'] = not saved_id
                                trial['checks'] = checks
                                trial['contract_passed'] = all(checks.values())
                            except Exception as exc:
                                trial['error_type'] = type(exc).__name__
                                trial['error'] = str(exc)[:200] if not isinstance(exc, httpx.HTTPError) else 'HTTP request failed'
                            trial['total_duration_ms'] = round((time.perf_counter() - started) * 1000)
                            trials.append(trial); file.write(json.dumps(trial, ensure_ascii=False) + '\n'); file.flush()
                            save_report(output, trials, manifest)
                            print(f"{case['id']} #{repetition + 1}: {'passed' if trial['contract_passed'] else 'failed'} {trial['total_duration_ms']} ms", flush=True)
            finally:
                templates = [{'case_id': t['case_id'], 'repetition': t['repetition'], 'review': {'assessor': 'human', 'task_completed': None, 'supported_claims': None, 'total_claims': None, 'notes': ''}} for t in trials]
                (output / 'reviews.template.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in templates), encoding='utf-8')
                if not args.keep_fixture:
                    await cleanup(uid, email, client)
                    manifest['fixture_cleaned'] = True
                save_report(output, trials, manifest)
    finally:
        await db.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('live', 'score', 'cleanup'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', default=str(DEFAULT_CASES))
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--allow-writes', action='store_true', help='允许独立测试账号创建会话和未发布草稿，默认结束后清理')
    parser.add_argument('--keep-fixture', action='store_true')
    parser.add_argument('--reviews')
    args = parser.parse_args()
    if args.repeats < 1 or args.limit < 1 or not 0 < args.timeout <= 600: parser.error('次数、limit 或 timeout 无效')
    output = Path(args.output).resolve()
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding='utf-8').splitlines() if line.strip()][:args.limit]
    if not cases or len({c['id'] for c in cases}) != len(cases): parser.error('样本必须非空且 ID 唯一')
    manifest = {'cases': len(cases), 'repeats': args.repeats, 'expected_trials': len(cases) * args.repeats,
                'cases_sha256': hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(), 'annotation_source': 'authored_smoke_contracts', 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    manifest['case_ids'] = [c['id'] for c in cases]
    code = hashlib.sha256()
    for path in sorted((ROOT / 'python-agent/app').rglob('*.py')):
        code.update(str(path.relative_to(ROOT)).encode()); code.update(path.read_bytes())
    manifest['agent_source_sha256'] = code.hexdigest()
    manifest['dependencies'] = {name: importlib.metadata.version(name) for name in ('langgraph', 'langchain-openai', 'httpx')}
    if args.command == 'score':
        manifest = json.loads((output / 'summary.json').read_text(encoding='utf-8'))['manifest']
        trials = [json.loads(line) for line in (output / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
        if args.reviews:
            reviews = {}
            for line in Path(args.reviews).read_text(encoding='utf-8').splitlines():
                item = json.loads(line); validate_review(item['review'])
                key = (item['case_id'], item['repetition'])
                if key in reviews: raise ValueError('重复评审')
                reviews[key] = item['review']
            if set(reviews) - {(t['case_id'], t['repetition']) for t in trials}: raise ValueError('评审不属于本次实验')
            for trial in trials:
                if (review := reviews.get((trial['case_id'], trial['repetition']))) is not None: trial['review'] = review
        print(json.dumps(save_report(output, trials, manifest), ensure_ascii=False, indent=2))
        return
    if not args.allow_writes: parser.error('live/cleanup 需要 --allow-writes，仅作用于独立本地测试账号')
    if args.command == 'live':
        if output.exists(): parser.error('使用全新输出目录以保留原始实验')
        output.mkdir(parents=True)
    asyncio.run(live(args, cases, output, manifest))


if __name__ == '__main__': main()
