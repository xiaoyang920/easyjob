"""Isolated, multi-turn full Agent journeys through the real local Java API."""
import argparse
import asyncio
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import re
import secrets
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from evaluation.e2e import cleanup, score, validate_review
from evaluation.metrics import percentile

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).with_name('datasets') / 'e2e.scenarios.jsonl'
BASE_URL = 'http://127.0.0.1:8080/api'


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def validate_scenarios(cases):
    ids = set()
    for case in cases:
        cid = case.get('id')
        if not isinstance(cid, str) or not cid or cid in ids:
            raise ValueError('场景ID必须非空且唯一')
        ids.add(cid)
        if not isinstance(case.get('category'), str) or not case['category'] or not case.get('review_rubric'):
            raise ValueError(f'{cid}: 需要场景类别与人工评审标准')
        steps = case.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValueError(f'{cid}: 每个场景需要1～20轮')
        for step in steps:
            if step.get('kind') != 'chat' or not isinstance(step.get('query'), str) or not 1 <= len(step['query']) <= 16000:
                raise ValueError(f'{cid}: chat消息需为1～16000字符')
            if step.get('transport', 'json') not in ('json', 'sse'):
                raise ValueError(f'{cid}: 未知传输方式')
            actions = step.get('approval_actions', [])
            if not isinstance(actions, list) or any(not isinstance(a, str) or not 1 <= len(a) <= 4000 for a in actions):
                raise ValueError(f'{cid}: 审批动作需为1～4000字符')
            if actions and (actions[-1] not in ('approve', 'reject') or any(a in ('approve', 'reject') for a in actions[:-1])):
                raise ValueError(f'{cid}: 修改意见后必须以唯一的批准或拒绝结束')
            if step.get('stale_approval_probe') and len(actions) < 2:
                raise ValueError(f'{cid}: 旧版本审批检测需要至少一次修改')
            for key in ('required_terms', 'required_nodes', 'relevant_documents'):
                if key in step and (not isinstance(step[key], list) or any(not isinstance(v, str) or not v for v in step[key])):
                    raise ValueError(f'{cid}: {key}需要非空字符串列表')
            if (step.get('origin_document') or step.get('relevant_documents')) and not case.get('requires_corpus'):
                raise ValueError(f'{cid}: 文章标签需要声明requires_corpus')
            if 'active_memory_counts' in step:
                counts = step['active_memory_counts']
                if not isinstance(counts, dict) or any(k not in ('constraint', 'decision') or isinstance(v, bool)
                        or not isinstance(v, int) or not 0 <= v <= 100 for k, v in counts.items()):
                    raise ValueError(f'{cid}: active_memory_counts需要有效类型和非负整数')
    if not cases: raise ValueError('场景不能为空')


def select_cases(cases, *, categories=(), limit=None, seed=42, include_web=False):
    candidates = [c for c in cases if (not categories or c['category'] in categories)
                  and (include_web or not c.get('requires_web'))]
    rng = random.Random(seed)
    # Round-robin categories before truncation: --limit does not select only the first 48 retrieval questions.
    buckets = {}
    for case in candidates: buckets.setdefault(case['category'], []).append(case)
    groups = list(buckets)
    rng.shuffle(groups)
    for group in groups: rng.shuffle(buckets[group])
    selected = []
    while any(buckets.values()):
        for group in groups:
            if buckets[group]: selected.append(buckets[group].pop())
    return selected if limit is None else selected[:limit]


class StreamCapture:
    """Parse real SSE frames, including arbitrary HTTP chunk boundaries."""
    def __init__(self):
        self.data_lines, self.text, self.events, self.frames = [], [], [], []
        self.answer = {'citations': []}
        self.pending = None
        self.started = self.ended = False
        self.seq = 0
        self.first_event_ms = self.first_answer_ms = None

    def line(self, line, elapsed_ms):
        if line.startswith('data:'):
            self.data_lines.append(line[5:].lstrip(' '))
        elif not line and self.data_lines:
            self.frame('\n'.join(self.data_lines), elapsed_ms)
            self.data_lines.clear()

    def finish(self, elapsed_ms):
        if self.data_lines:
            self.frame('\n'.join(self.data_lines), elapsed_ms)
            self.data_lines.clear()

    def frame(self, data, elapsed_ms):
        if self.first_event_ms is None: self.first_event_ms = round(elapsed_ms)
        if data.startswith('[ERROR]'): raise RuntimeError('stream_error:' + data[7:][:160])
        tag, _, raw = data.partition(':')
        self.frames.append(tag)
        if tag == '__CONV_ID__': self.answer['conversationId'] = raw
        elif tag == '__RUN_ID__': self.answer['runId'] = raw
        elif tag == '__INTERRUPTED__': self.pending = json.loads(raw)
        elif tag == '__CITATIONS__': self.answer['citations'] = json.loads(raw)
        elif tag == '__AGENT_EVENT__': self.events.append(json.loads(raw))
        elif tag == '__DRAFT_SAVED__': self.answer['draftArticleId'] = json.loads(raw)['draftArticleId']
        elif tag == '__ANSWER__':
            value = json.loads(raw)
            if value['type'] == 'start':
                if self.started: raise ValueError('duplicate_answer_start')
                self.started = True
            elif value['type'] == 'delta':
                if not self.started or self.ended or value['seq'] != self.seq: raise ValueError('invalid_answer_sequence')
                if self.first_answer_ms is None: self.first_answer_ms = round(elapsed_ms)
                self.seq += 1
                self.text.append(value['content'])
            elif value['type'] == 'end':
                if not self.started or self.ended or value['chunks'] != self.seq: raise ValueError('invalid_answer_end')
                self.ended = True

    def result(self):
        if not self.answer.get('runId') or not self.answer.get('conversationId'): raise ValueError('missing_stream_identity')
        if not self.pending and not self.ended: raise ValueError('incomplete_answer_stream')
        self.answer['reply'] = ''.join(self.text)
        return self.answer


def contract_checks(step, answer, status, events, document_ids):
    citations = answer.get('citations') or []
    reply = answer.get('reply') or ''
    cited = set(re.findall(r'\[([a-z][a-z0-9_]*:(?:web)?\d+)\]', reply))
    known = {c.get('id') for c in citations}
    checks = {'succeeded': status == 'succeeded', 'nonempty_reply': bool(reply.strip()),
              'citation_ids_consistent': cited <= known}
    if step.get('required_citations'):
        checks['citations_present'] = bool(citations)
        checks['citations_used_in_reply'] = bool(cited)
    if step.get('required_nodes'):
        checks['required_nodes'] = all(any(node in e['node'] for e in events) for node in step['required_nodes'])
    if step.get('required_terms'):
        checks['required_terms'] = all(term.casefold() in reply.casefold() for term in step['required_terms'])
    if step.get('relevant_documents'):
        expected = {document_ids[key] for key in step['relevant_documents']}
        used = {str(c.get('articleId')) for c in citations if c.get('id') in cited}
        checks['labelled_article_used'] = bool(used & expected)
    if step.get('require_web_citations'):
        checks['web_source_used'] = any(c.get('id') in cited and urlparse(c.get('url') or '').scheme in ('http', 'https')
                                        and not c.get('articleId') for c in citations)
    return checks


def aggregate_run_metrics(runs):
    """Each run's latest cumulative snapshot once; approvals/replays must not double count."""
    snapshots = list(runs.values())
    complete = bool(snapshots) and all(m and m.get('token_usage_complete') for m in snapshots)
    return {'token_usage_complete': complete,
            'input_tokens': sum(m['input_tokens'] for m in snapshots) if complete else None,
            'output_tokens': sum(m['output_tokens'] for m in snapshots) if complete else None,
            'llm_calls': sum(m.get('llm_calls', 0) for m in snapshots if m),
            'run_count': len(snapshots), 'runs_missing_usage': sum(not m or not m.get('token_usage_complete') for m in snapshots)}


def stale_probe_checks(code, status, articles, approved_ids):
    """Transport contract and safety are distinct: a masked 409 is not an unauthorized save."""
    return {'stale_approval_conflict_status': code == 409,
            'stale_approval_kept_pending': status == 'awaiting_approval',
            'stale_approval_no_save': {str(a['article_id']) for a in articles if not a['deleted']} == approved_ids}


def revision_changed(before, after):
    """A satisfied revision may be a no-op; content hashes must remain honest."""
    if not after or after.get('runId') != before.get('runId') or not after.get('draftHash'):
        raise RuntimeError('revision_did_not_reinterrupt')
    changed = any(before.get(key) != after.get(key) for key in ('title', 'summary', 'draft'))
    if changed != (before['draftHash'] != after['draftHash']):
        raise RuntimeError('revision_hash_content_mismatch')
    return changed


def summarize(cases, trials, repeats):
    planned = {(c['id'], rep): c for c in cases for rep in range(repeats)}
    seen = set()
    for t in trials:
        key = (t['case_id'], t['repetition'])
        if key not in planned or key in seen: raise ValueError('未知、重复或超出计划的实验记录')
        seen.add(key)
    result = score(trials, len(planned))
    result.update(total_latency_p50_ms_all_recorded=percentile([t['total_duration_ms'] for t in trials], 50),
                  timed_out=sum(t.get('error_type') in ('TimeoutError', 'ReadTimeout', 'ConnectTimeout', 'PoolTimeout')
                                or any(s.get('error_type') in ('TimeoutError', 'ReadTimeout', 'ConnectTimeout', 'PoolTimeout') for s in t.get('steps', [])) for t in trials),
                  error_types=dict(Counter(t.get('error_type', 'contract_mismatch') for t in trials if not t['contract_passed'])),
                  failure_reasons=dict(Counter(t.get('error', 'contract_mismatch') for t in trials if not t['contract_passed'])),
                  user_turns_planned=sum(len(c['steps']) for c in cases) * repeats,
                  user_turns_recorded=sum(len(t.get('steps', [])) for t in trials),
                  llm_calls_measured=sum((t.get('metrics') or {}).get('llm_calls', 0) for t in trials),
                  categories={})
    for category in sorted({c['category'] for c in cases}):
        expected = sum(c['category'] == category for c in cases) * repeats
        group = [t for t in trials if planned[t['case_id'], t['repetition']]['category'] == category]
        result['categories'][category] = {**score(group, expected),
            'latency_p50_ms': percentile([t['total_duration_ms'] for t in group], 50)}
    steps = [s for t in trials for s in t.get('steps', [])]
    result['step_contract_pass_rate_planned'] = sum(s.get('contract_passed', False) for s in steps) / result['user_turns_planned']
    result['step_latency_p50_ms'] = percentile([s['duration_ms'] for s in steps], 50)
    result['step_latency_p95_ms'] = percentile([s['duration_ms'] for s in steps], 95)
    result['failed_checks'] = dict(Counter(k for s in steps for k, passed in s.get('checks', {}).items() if not passed))
    return result


def save_reports(output, cases, trials, manifest):
    summary = summarize(cases, trials, manifest['repeats'])
    (output / 'summary.json').write_text(json.dumps({'manifest': manifest, **summary}, ensure_ascii=False, indent=2), encoding='utf-8')
    fmt = lambda n: '未测量' if n is None else f'{n:.2f}'
    rows = '\n'.join(f"| {name} | {v['recorded_trials']}/{v['expected_trials']} | {v['automatic_contract_passed']} | {fmt(v['latency_p50_ms'])} | {fmt(v['total_latency_p95_ms_all_recorded'])} |"
                     for name, v in summary['categories'].items())
    text = f'''# 多轮完整 Agent 场景评测

数据来源：合成、预先编写的产品场景，非真实用户日志。{len(cases)} 个场景 × {manifest['repeats']} 次；
计划 {summary['user_turns_planned']} 轮用户提问，已记录 {summary['user_turns_recorded']} 轮。
并发场景数 {manifest['concurrency']}，seed={manifest['seed']}；不得直接与并发1的旧P95比较。

| 指标 | 结果 |
|---|---:|
| 场景契约通过 / 计划 | {summary['automatic_contract_passed']}/{summary['expected_trials']} |
| 已记录 / 计划 | {summary['recorded_trials']}/{summary['expected_trials']} |
| 多轮场景 P50 / P95（ms） | {fmt(summary['total_latency_p50_ms_all_recorded'])} / {fmt(summary['total_latency_p95_ms_all_recorded'])} |
| 单轮完整执行 P50 / P95（ms） | {fmt(summary['step_latency_p50_ms'])} / {fmt(summary['step_latency_p95_ms'])} |
| 超时场景 | {summary['timed_out']} |
| Token完整计量场景 / 计划 | {summary['token_usage_measured_trials']}/{summary['expected_trials']} |
| 已计量输入 / 输出Token | {summary['input_tokens_measured']} / {summary['output_tokens_measured']} |
| 人工已评审 / 待评审 | {summary['human_reviewed_trials']} / {summary['human_review_pending']} |

| 类别 | 已记录/计划 | 契约通过 | 场景P50 ms | 场景P95 ms |
|---|---:|---:|---:|---:|
{rows}

失败、超时和未完成样本保留在分母；已有部分结果不能伪装成完整任务成功。
每个场景独立账号；同一场景沿用会话，只有显式跨会话记忆步骤新建会话。
草稿每次暂停都核对数据库未提前保存；修改后核对内容与hash一致性，有内容变更时旧审批失效；无变更仍需审批；批准只产生未发布草稿。
已计量Token对每个run取最新累计值，审批恢复不重复相加；缺失usage为未知。
耗时包含HTTP、模型、工具及审批恢复，不含测试账号准备/清理，脚本立即审批，不含人为等待。
场景和单轮耗时也包含必要的数据库验证，以及标记场景等待后台提取完成的时间。
SSE记录首事件/首答案时间，当前首答案为校验后的最终答案片段，不能称为模型首Token时间。
文章标签命中仅表示使用了已标注相关文章，不能证明每条引用支持结论。
安全、无结果、歧义、记忆遵循和答案事实质量需要按照 review_rubric 人工复核；默认全量待评审。
本数据不包含真实图片理解、服务进程重启、故障注入或96K压缩负载，不能据此声称这些场景已通过。

参阅 predictions.jsonl 的每轮答案、来源、事件、记忆及草稿状态；failures.jsonl 保留失败定位记录。
'''
    (output / 'report.md').write_text(text, encoding='utf-8')
    (output / 'failures.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in trials if not t['contract_passed']), encoding='utf-8')
    templates = [{'case_id': t['case_id'], 'repetition': t['repetition'],
                  'review_rubric': next(c['review_rubric'] for c in cases if c['id'] == t['case_id']),
                  'review': {'assessor': 'human', 'task_completed': None, 'supported_claims': None, 'total_claims': None, 'notes': ''}} for t in trials]
    (output / 'reviews.template.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in templates), encoding='utf-8')
    return summary


async def business(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    body = response.json()
    if body.get('code') != 200: raise RuntimeError('business_code:' + str(body.get('code')))
    return body['data']


async def request_answer(client, path, payload, transport, record):
    started = time.perf_counter()
    if transport == 'json':
        answer = await business(client, 'POST', path, json=payload)
        pending = None
        try:
            value = json.loads(answer.get('reply') or '')
            if isinstance(value, dict) and value.get('interrupted'): pending = value['payload']
        except (TypeError, ValueError): pass
        return answer, pending
    capture = StreamCapture()
    try:
        async with client.stream('POST', path + '/stream', json=payload) as response:
            response.raise_for_status()
            if 'text/event-stream' not in response.headers.get('content-type', ''): raise RuntimeError('not_sse_response')
            async for line in response.aiter_lines(): capture.line(line, (time.perf_counter() - started) * 1000)
            capture.finish((time.perf_counter() - started) * 1000)
        return capture.result(), capture.pending
    finally:
        record.setdefault('streams', []).append({'first_event_ms': capture.first_event_ms,
            'first_answer_ms': capture.first_answer_ms, 'frames': capture.frames, 'events': capture.events})
        # Preserve identities even on partial stream failure, for cancellation/diagnosis.
        record.update({k: v for k, v in capture.answer.items() if k in ('runId', 'conversationId')})


async def memory_snapshot(db, uid):
    profile = await db.fetch_one('SELECT tech_stack,interests,experience,preferences FROM user_profile WHERE user_id=:uid', {'uid': uid})
    rows = await db.fetch_all('SELECT memory_id,memory_type,scope,scope_conversation_id,status,memory_key,content FROM user_memory WHERE user_id=:uid ORDER BY memory_id', {'uid': uid})
    return {'profile': dict(profile._mapping) if profile else None, 'records': [dict(r._mapping) for r in rows]}


async def article_snapshot(db, uid):
    rows = await db.fetch_all('SELECT article_id,title,status,deleted FROM article_info WHERE user_id=:uid ORDER BY article_id', {'uid': uid})
    return [dict(r._mapping) for r in rows]


async def capture_run(db, uid, rid, run_metrics):
    row = await db.fetch_one('SELECT status,result_json FROM agent_run WHERE user_id=:uid AND run_id=:rid', {'uid': uid, 'rid': rid})
    if not row: raise RuntimeError('missing_owned_run')
    result = json.loads(row['result_json']) if row['result_json'] else {}
    run_metrics[rid] = result.get('metrics')
    events = await db.fetch_all('SELECT node,status,duration_ms FROM agent_run_event WHERE run_id=:rid ORDER BY event_id', {'rid': rid})
    return row['status'], result, [dict(e._mapping) for e in events]


async def capture_sources(db, citations):
    """Re-read public article versions; snapshots allow independent citation review."""
    snapshots, valid = {}, True
    for citation in citations:
        aid = citation.get('articleId')
        if not aid or str(aid) in snapshots: continue
        row = await db.fetch_one('SELECT title,content,status,deleted FROM article_info WHERE article_id=:aid', {'aid': int(aid)})
        if not row or row['status'] != 1 or row['deleted']:
            valid = False
            snapshots[str(aid)] = {'availability': 'unavailable'}
        else:
            fingerprint = hashlib.sha256(row['content'].encode()).hexdigest()
            snapshots[str(aid)] = {'title': row['title'], 'content': row['content'], 'source_hash': fingerprint}
    for c in citations:
        if c.get('articleId') and c.get('sourceHash') != snapshots[str(c['articleId'])].get('source_hash'):
            valid = False
    return snapshots, valid


async def validate_corpus(db, cases, path):
    if not any(c.get('requires_corpus') for c in cases): return {}, None
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    targets = {key for c in cases for s in c['steps'] for key in s.get('relevant_documents', [])}
    targets |= {s['origin_document'] for c in cases for s in c['steps'] if s.get('origin_document')}
    if any(c['category'] == 'no_result' for c in cases): targets |= set(manifest['samples'])
    mapping = {}
    for key in targets:
        source = manifest['samples'][key]
        row = await db.fetch_one('SELECT user_id,content,status,deleted FROM article_info WHERE article_id=:aid', {'aid': int(source['article_id'])})
        if not row or row['user_id'] != manifest['author_id'] or row['status'] != 1 or row['deleted'] or hashlib.sha256(row['content'].encode()).hexdigest() != source['source_hash']:
            raise RuntimeError('样例文章缺失或已修改：' + key + '；先用 evaluation.local_samples seed 检查语料')
        mapping[key] = str(source['article_id'])
    return mapping, hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def create_fixture(db, case, repetition):
    from app.utils.snowflake import snowflake
    uid, suffix = snowflake.next_id(), secrets.token_hex(8)
    email = f'e2e-{suffix}@sample.invalid'
    await db.execute('''INSERT INTO user_info(user_id,nick_name,email,password,person_introduction,join_time,
        sex,status,article_count,total_coin_count,current_coin_count,theme,role,follower_count,following_count,data_source)
        VALUES(:uid,:name,:email,:password,'临时端到端评测账号',NOW(),2,1,0,0,0,1,1,0,0,'evaluation')''',
        {'uid': uid, 'name': '场景评测' + suffix[:10], 'email': email, 'password': secrets.token_urlsafe(40)})
    return {'uid': uid, 'email': email, 'case_id': case['id'], 'repetition': repetition, 'cleaned': False}


async def execute_scenario(case, repetition, client, db, uid, document_ids, timeout):
    from app.config import settings
    trial = {'case_id': case['id'], 'category': case['category'], 'repetition': repetition,
             'contract_passed': False, 'steps': [], 'review_rubric': case['review_rubric']}
    cid, run_metrics, saved_ids = None, {}, set()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            for index, step in enumerate(case['steps']):
                record = {'index': index, 'query': step['query'], 'contract_passed': False,
                          'transport': step.get('transport', 'json'), 'checks': {}}
                trial['steps'].append(record)
                turn_started = time.perf_counter()
                try:
                    payload = {'message': step['query'], 'requestId': str(uuid4())}
                    if cid and not step.get('new_conversation'): payload['conversationId'] = cid
                    if step.get('origin_document'): payload['originArticleId'] = document_ids[step['origin_document']]
                    record['memory_before'] = await memory_snapshot(db, uid)
                    answer, pending = await request_answer(client, '/agent/chat', payload, record['transport'], record)
                    cid, rid = answer['conversationId'], answer['runId']
                    record.update(conversation_id=cid, run_id=rid, interrupted=bool(pending))
                    actions = step.get('approval_actions', [])
                    if not pending and actions and not step.get('approval_optional'): raise RuntimeError('expected_draft_approval')
                    if pending and not actions:
                        # Finish the unexpected approval without writing, then mark the original contract failed.
                        await business(client, 'POST', '/agent/chat/resume', json={'conversationId': cid,
                            'runId': rid, 'draftHash': pending['draftHash'], 'action': 'reject'})
                        raise RuntimeError('unexpected_draft_approval')
                    previous_hash = None
                    record['approvals'] = []
                    if pending:
                        for action in actions:
                            if not pending: raise RuntimeError('missing_revised_approval')
                            articles = await article_snapshot(db, uid)
                            if {str(a['article_id']) for a in articles if not a['deleted']} != saved_ids:
                                raise RuntimeError('draft_saved_before_approval')
                            approval = {'action': action, 'hash': pending['draftHash'], 'title': pending.get('title'),
                                        'draft': pending.get('draft'), 'articles_before': articles}
                            record['approvals'].append(approval)
                            if previous_hash and step.get('stale_approval_probe'):
                                probe = await client.post('/agent/chat/resume', json={'conversationId': cid, 'runId': rid,
                                    'draftHash': previous_hash, 'action': 'approve'})
                                code = probe.status_code if probe.status_code != 200 else probe.json().get('code')
                                approval['stale_probe_code'] = code
                                probe_status, _, _ = await capture_run(db, uid, rid, run_metrics)
                                probe_articles = await article_snapshot(db, uid)
                                approval.update(stale_probe_run_status=probe_status, articles_after_stale_probe=probe_articles)
                                probe_checks = stale_probe_checks(code, probe_status, probe_articles, saved_ids)
                                for key, passed in probe_checks.items():
                                    record['checks'][key] = record['checks'].get(key, True) and passed
                                if not probe_checks['stale_approval_kept_pending'] or not probe_checks['stale_approval_no_save']:
                                    raise RuntimeError('stale_approval_changed_business_state')
                                # Continue the valid approval after a transport mismatch to collect the
                                # remaining lifecycle evidence. The scene still fails its contract.
                            old_hash = pending['draftHash']
                            previous_draft = pending
                            answer, pending = await request_answer(client, '/agent/chat/resume', {'conversationId': cid,
                                'runId': rid, 'draftHash': old_hash, 'action': action}, record['transport'], record)
                            if action not in ('approve', 'reject'):
                                approval['revision_changed'] = revision_changed(previous_draft, pending)
                                previous_hash = old_hash if approval['revision_changed'] else None
                            elif pending: raise RuntimeError('terminal_approval_still_pending')
                    status, ledger, events = await capture_run(db, uid, rid, run_metrics)
                    record.update(reply=answer.get('reply'), citations=answer.get('citations') or [],
                                  run_status=status, events=events, metrics=run_metrics[rid])
                    record['checks'].update(contract_checks(step, answer, status, events, document_ids))
                    record['checks']['ledger_reply_matches'] = ledger.get('reply') == answer.get('reply')
                    sources, valid = await capture_sources(db, record['citations'])
                    record['source_snapshots'] = sources
                    record['checks']['evidence_versions_valid'] = valid
                    rounds = [int(m.group(1)) for e in events if (m := re.match(r'round_(\d+)\.main_agent$', e['node']))]
                    record['checks']['rounds_bounded'] = max(rounds, default=0) <= settings.MAIN_MAX_ROUNDS
                    saved = answer.get('draftArticleId')
                    if saved: saved_ids.add(str(saved))
                    articles = await article_snapshot(db, uid)
                    record['articles_after'] = articles
                    if step.get('wait_background_extract'):
                        deadline = time.monotonic() + 20
                        while True:
                            jobs = await db.fetch_all("SELECT kind,status,attempts FROM agent_background_job WHERE user_id=:uid AND conversation_id=:cid AND kind='memory_extract'", {'uid': uid, 'cid': int(cid)})
                            record['background_jobs'] = [dict(j._mapping) for j in jobs]
                            if jobs and all(j['status'] == 'completed' for j in jobs): break
                            if time.monotonic() >= deadline: break
                            await asyncio.sleep(.5)
                        record['checks']['background_extraction_jobs_completed'] = bool(jobs) and all(j['status'] == 'completed' for j in jobs)
                    record['memory_after'] = await memory_snapshot(db, uid)
                    for kind, expected in step.get('active_memory_counts', {}).items():
                        record['checks']['active_' + kind + '_count'] = sum(
                            m['memory_type'] == kind and m['status'] == 'active'
                            for m in record['memory_after']['records']) == expected
                    if step.get('forbid_event_extraction'):
                        record['checks']['ordinary_chat_no_memory_changes'] = record['memory_after'] == record['memory_before']
                        record['checks']['ordinary_chat_no_events'] = not any(
                            m.get('memory_type') == 'event' for m in record['memory_after'].get('records', []))
                        record['checks']['no_extraction_jobs'] = not await db.fetch_val(
                            "SELECT COUNT(*) FROM agent_background_job WHERE user_id=:uid AND kind='memory_extract'", {'uid': uid})
                    record['checks']['no_published_articles'] = all(a['status'] == 0 for a in articles)
                    record['checks']['no_unapproved_saves'] = {str(a['article_id']) for a in articles if not a['deleted']} == saved_ids
                    if record['approvals'] and actions[-1] == 'approve':
                        record['checks']['approved_draft_persisted'] = bool(saved and any(str(a['article_id']) == str(saved) and a['status'] == 0 and not a['deleted'] for a in articles))
                    if record['approvals'] and actions[-1] == 'reject': record['checks']['rejected_not_saved'] = not saved
                    record['contract_passed'] = all(record['checks'].values())
                    if not record['contract_passed']: raise RuntimeError('contract_mismatch')
                except Exception as exc:
                    record['error_type'] = type(exc).__name__
                    record['error'] = str(exc)[:240] if not isinstance(exc, httpx.HTTPError) else 'HTTP request failed'
                    raise
                finally:
                    record['duration_ms'] = round((time.perf_counter() - turn_started) * 1000)
            trial['contract_passed'] = all(s['contract_passed'] for s in trial['steps'])
    except Exception as exc:
        trial['error_type'] = type(exc).__name__
        trial['error'] = str(exc)[:240] if not isinstance(exc, httpx.HTTPError) else 'HTTP request failed'
        # Include any partial/failed run without inventing missing usage.
        rows = await db.fetch_all('SELECT run_id,status,result_json,conversation_id FROM agent_run WHERE user_id=:uid', {'uid': uid})
        for row in rows:
            result = json.loads(row['result_json']) if row['result_json'] else {}
            run_metrics[row['run_id']] = result.get('metrics')
            if row['status'] == 'running':
                try: await client.post('/agent/chat/' + str(row['conversation_id']) + '/cancel')
                except httpx.HTTPError: pass
    finally:
        trial['total_duration_ms'] = round((time.perf_counter() - started) * 1000)
        trial['metrics'] = aggregate_run_metrics(run_metrics)
    return trial


async def cleanup_fixtures(db, output, fixtures, manifest):
    from evaluation.local_samples import local_token
    for fixture in fixtures:
        if fixture.get('cleaned'): continue
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60, trust_env=False,
                headers={'Authorization': 'Bearer ' + local_token(fixture['uid'])}) as client:
            try:
                # A prior interrupted CLI may still have an active server run.
                rows = await db.fetch_all("SELECT conversation_id FROM agent_run WHERE user_id=:uid AND status='running'", {'uid': fixture['uid']})
                for row in rows: await client.post('/agent/chat/' + str(row['conversation_id']) + '/cancel')
                await cleanup(fixture['uid'], fixture['email'], client)
                fixture['cleaned'] = True
                fixture.pop('cleanup_error', None)
            except Exception as exc:
                fixture['cleanup_error'] = type(exc).__name__
            (output / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest['fixture_cleaned'] = all(f.get('cleaned') for f in fixtures)
    manifest['cleanup_pending'] = sum(not f.get('cleaned') for f in fixtures)


async def live(args, output, cases, manifest):
    from app.clients.mysql_client import db
    from evaluation.local_samples import local_token
    await db.connect()
    fixtures = json.loads((output / 'fixtures.json').read_text(encoding='utf-8')) if (output / 'fixtures.json').exists() else []
    trials = read_jsonl(output / 'predictions.jsonl') if (output / 'predictions.jsonl').exists() else []
    try:
        if args.command == 'cleanup':
            await cleanup_fixtures(db, output, fixtures, manifest)
            save_reports(output, cases, trials, manifest)
            if manifest['cleanup_pending']: raise RuntimeError('部分清理失败，检查fixtures.json并重试cleanup')
            print('All isolated scenario fixtures cleaned.', flush=True)
            return
        documents, corpus_hash = await validate_corpus(db, cases, args.corpus_manifest)
        manifest['corpus_manifest_sha256'] = corpus_hash
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10, trust_env=False) as health:
            await business(health, 'GET', '/article/list')
        semaphore = asyncio.Semaphore(args.concurrency)
        completed = {(t['case_id'], t['repetition']) for t in trials}

        async def one(case, repetition):
            async with semaphore:
                fixture = await create_fixture(db, case, repetition)
                fixtures.append(fixture)
                (output / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding='utf-8')
                async with httpx.AsyncClient(base_url=BASE_URL, timeout=args.timeout, trust_env=False,
                        headers={'Authorization': 'Bearer ' + local_token(fixture['uid'])}) as client:
                    trial = await execute_scenario(case, repetition, client, db, fixture['uid'], documents, args.timeout)
                trials.append(trial)
                with (output / 'predictions.jsonl').open('a', encoding='utf-8') as file:
                    file.write(json.dumps(trial, ensure_ascii=False, default=str) + '\n')
                save_reports(output, cases, trials, manifest)
                print(f"{len(trials)}/{manifest['expected_trials']} {case['id']} #{repetition + 1}: "
                      f"{'passed' if trial['contract_passed'] else 'FAILED'} {trial['total_duration_ms']} ms "
                      f"{trial.get('error', '')}", flush=True)
        try:
            tasks = [asyncio.create_task(one(case, rep)) for rep in range(args.repeats) for case in cases
                     if (case['id'], rep) not in completed]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Fixture preparation errors remain unrecorded, hence count as missing/failed in the plan.
            manifest['runner_errors'] = [type(r).__name__ for r in results if isinstance(r, BaseException)]
        finally:
            if not args.keep_fixture: await cleanup_fixtures(db, output, fixtures, manifest)
            save_reports(output, cases, trials, manifest)
        if manifest.get('runner_errors') or manifest.get('cleanup_pending'):
            raise RuntimeError('评测执行或清理未完整完成，请检查summary.json和fixtures.json')
    except Exception as exc:
        manifest['execution_error_type'] = type(exc).__name__
        save_reports(output, cases, trials, manifest)
        raise
    finally:
        await db.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'live', 'score', 'cleanup'))
    parser.add_argument('--cases', default=str(DATA))
    parser.add_argument('--output')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--categories', nargs='+', default=[])
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=240, help='每个完整场景总时限，包含多轮及审批')
    parser.add_argument('--include-web', action='store_true', help='联网类场景调用第三方搜索，默认不选入计划')
    parser.add_argument('--allow-writes', action='store_true')
    parser.add_argument('--keep-fixture', action='store_true')
    parser.add_argument('--continue-run', action='store_true', help='仅补跑中断后未记录的场景，不重跑已记录失败')
    parser.add_argument('--corpus-manifest', default=str(ROOT / 'logs/evaluation/sample-corpus-v1/manifest.json'))
    parser.add_argument('--reviews')
    parser.add_argument('--fail-on-contract', action='store_true', help='任一失败/缺失场景使进程返回非零，报告仍保留')
    args = parser.parse_args()
    if args.repeats < 1 or args.limit is not None and args.limit < 1 or not 1 <= args.concurrency <= 4 or not 0 < args.timeout <= 600:
        parser.error('repeats/limit需为正数，并发1～4，场景总时限1～600秒')
    output = Path(args.output).resolve() if args.output else None
    # Score/cleanup rely exclusively on the frozen plan, even if the current dataset is removed.
    plan_only = args.command in ('score', 'cleanup')
    all_cases = read_jsonl(output / 'cases.frozen.jsonl' if plan_only and output else args.cases)
    validate_scenarios(all_cases)
    unknown = set(args.categories) - {c['category'] for c in all_cases}
    if unknown: parser.error('未知类别：' + ','.join(sorted(unknown)))
    cases = all_cases if plan_only else select_cases(all_cases, categories=args.categories, limit=args.limit, seed=args.seed, include_web=args.include_web)
    validate_scenarios(cases)
    manifest = {'cases': len(cases), 'case_ids': [c['id'] for c in cases], 'repeats': args.repeats,
                'expected_trials': len(cases) * args.repeats, 'concurrency': args.concurrency, 'seed': args.seed,
                'include_web': args.include_web, 'annotation_source': 'synthetic_authored_journeys',
                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'dataset_sha256': hashlib.sha256((output / 'cases.frozen.jsonl' if plan_only else Path(args.cases)).read_bytes()).hexdigest()}
    if args.command == 'validate':
        print(json.dumps({'scenarios': len(cases), 'user_turns': sum(len(c['steps']) for c in cases),
                          'categories': dict(Counter(c['category'] for c in cases)), 'manifest': manifest}, ensure_ascii=False, indent=2))
        return
    if not args.output: parser.error('需要 --output')
    output = Path(args.output).resolve()
    if args.command in ('score', 'cleanup') or args.continue_run:
        old = json.loads((output / 'summary.json').read_text(encoding='utf-8'))['manifest']
        cases = read_jsonl(output / 'cases.frozen.jsonl')
        validate_scenarios(cases)
        if hashlib.sha256((output / 'cases.frozen.jsonl').read_bytes()).hexdigest() != old['selected_cases_sha256']:
            parser.error('冻结的测试标签已改变，不能继续沿用原计划')
        if args.continue_run:
            for key in ('case_ids', 'repeats', 'concurrency', 'seed', 'include_web', 'dataset_sha256'):
                if old[key] != manifest[key]: parser.error('续跑配置与冻结计划不一致：' + key)
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != old['runner_source_sha256']:
                parser.error('评测程序已改变，使用新目录启动实验')
            code = hashlib.sha256()
            for path in sorted((ROOT / 'python-agent/app').rglob('*.py')):
                code.update(str(path.relative_to(ROOT)).encode()); code.update(path.read_bytes())
            if code.hexdigest() != old['agent_source_sha256']: parser.error('Agent源码已改变，使用新目录启动实验')
        manifest = old
    if args.command == 'score':
        trials = read_jsonl(output / 'predictions.jsonl')
        reviews_path = Path(args.reviews) if args.reviews else output / 'reviews.applied.jsonl'
        if reviews_path.exists():
            reviews = {}
            for item in read_jsonl(reviews_path):
                validate_review(item['review'])
                key = (item['case_id'], item['repetition'])
                if key in reviews: raise ValueError('重复人工评审')
                reviews[key] = item['review']
            if set(reviews) - {(t['case_id'], t['repetition']) for t in trials}: raise ValueError('评审不属于本次实验')
            for t in trials:
                if (review := reviews.get((t['case_id'], t['repetition']))) is not None: t['review'] = review
            (output / 'reviews.applied.jsonl').write_text(reviews_path.read_text(encoding='utf-8'), encoding='utf-8')
        elif args.reviews: parser.error('人工评审文件不存在')
        print(json.dumps(save_reports(output, cases, trials, manifest), ensure_ascii=False, indent=2))
        return
    if not args.allow_writes: parser.error('live/cleanup需要--allow-writes，仅写独立本地评测账号和未发布草稿')
    if args.command == 'live' and not args.continue_run:
        if output.exists(): parser.error('输出目录已存在，请新建或使用--continue-run')
        output.mkdir(parents=True)
        (output / 'cases.frozen.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')
        manifest['selected_cases_sha256'] = hashlib.sha256((output / 'cases.frozen.jsonl').read_bytes()).hexdigest()
        code = hashlib.sha256()
        for path in sorted((ROOT / 'python-agent/app').rglob('*.py')):
            code.update(str(path.relative_to(ROOT)).encode()); code.update(path.read_bytes())
        manifest['agent_source_sha256'] = code.hexdigest()
        manifest['runner_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (output / 'runner.snapshot.py').write_bytes(Path(__file__).read_bytes())
        manifest['dependencies'] = {name: importlib.metadata.version(name) for name in ('langgraph', 'langchain-openai', 'httpx')}
        save_reports(output, cases, [], manifest)
    asyncio.run(live(args, output, cases, manifest))
    if args.fail_on_contract and args.command == 'live':
        summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
        if summary['automatic_contract_passed'] != summary['expected_trials']: raise SystemExit(1)


if __name__ == '__main__': main()
