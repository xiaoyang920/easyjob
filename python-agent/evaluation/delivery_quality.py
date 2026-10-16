"""Frozen delivery evaluation: collect candidate/final answers, then score independent human reviews."""
import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from evaluation.delivery_cases import cases
from evaluation.metrics import percentile


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def summarize(rows, reviews, expected, mode):
    by_id = {row['id']: row for row in rows}
    if len(by_id) != len(rows) or len(rows) > expected:
        raise ValueError('Duplicate or unexpected evaluation records')
    reviewed = []
    seen = set()
    for review in reviews:
        key = review['id']
        if key in seen or key not in by_id:
            raise ValueError('Duplicate or unknown review')
        seen.add(key)
        # Empty templates remain pending; never turn missing labels into zero or success.
        if review.get('reviewer') is None:
            continue
        if mode != 'live' or review.get('assessor') != 'human' or not isinstance(review['reviewer'], str) or not review['reviewer'].strip():
            raise ValueError('Quality metrics require named human review of live outputs')
        row = by_id[key]
        if review.get('candidate_hash') != digest(row.get('candidate_reply', '')) or review.get('final_hash') != digest(row.get('reply', '')):
            raise ValueError('Review does not match frozen output')
        if row.get('error_type') or not isinstance(review.get('task_completed'), bool) or not isinstance(review.get('context_coherent'), bool):
            raise ValueError('Cannot review failed/malformed output')
        for numerator, denominator in [('falsely_blocked_units', 'candidate_correct_units'), ('unsupported_specific_facts', 'specific_facts')]:
            n, d = review.get(numerator), review.get(denominator)
            if type(n) is not int or type(d) is not int or not 0 <= n <= d:
                raise ValueError('Invalid human unit counts')
        reviewed.append(review)
    token_rows = [row for row in rows if (row.get('metrics') or {}).get('token_usage_complete')]
    candidate_correct = sum(r['candidate_correct_units'] for r in reviewed)
    facts = sum(r['specific_facts'] for r in reviewed)
    contract_passed = sum(not row.get('error_type') and bool(row.get('reply'))
        and (row.get('main_decision') or {}).get('action') == 'answer'
        and (row.get('assertions') or {}).get('not_contract_stop') is True
        and not row.get('blocked_calls')
        and (row.get('audit') or {}).get('status') in ('verified', 'repaired', 'not_required') for row in rows)
    return {'mode': mode, 'expected_trials': expected, 'recorded_trials': len(rows),
        'error_trials': sum(bool(r.get('error_type')) for r in rows), 'missing_trials': expected-len(rows),
        'automatic_delivery_contract_passed_trials': contract_passed,
        'automatic_delivery_contract_failed_or_missing_trials': expected-contract_passed,
        'automatic_contract_scope': 'answer action, nonempty delivery, no contract stop or external writes, delivery gate completed/skipped by policy; not semantic accuracy',
        'human_reviewed_trials': len(reviewed), 'human_review_pending': expected-len(reviewed),
        'task_completion_rate_reviewed_only': sum(r['task_completed'] for r in reviewed)/len(reviewed) if reviewed else None,
        'context_coherence_rate_reviewed_only': sum(r['context_coherent'] for r in reviewed)/len(reviewed) if reviewed else None,
        'false_block_rate_reviewed_only': sum(r['falsely_blocked_units'] for r in reviewed)/candidate_correct if candidate_correct else None,
        'unsupported_specific_fact_rate_reviewed_only': sum(r['unsupported_specific_facts'] for r in reviewed)/facts if facts else None,
        'latency_p50_ms_all_recorded': percentile([r['duration_ms'] for r in rows], 50),
        'latency_p95_ms_all_recorded': percentile([r['duration_ms'] for r in rows], 95),
        'tokens_measured_trials': len(token_rows),
        'input_tokens_measured': sum(r['metrics']['input_tokens'] for r in token_rows) if token_rows else None,
        'output_tokens_measured': sum(r['metrics']['output_tokens'] for r in token_rows) if token_rows else None,
        'llm_calls': sum((r.get('metrics') or {}).get('llm_calls', 0) for r in rows) if mode == 'live' else 0,
        'note': '问题改写自已提供的技术对话，并补充人工编写边界样例；不是生产日志或独立留出集。来源为冻结资料，不执行真实检索。replay仅验证流程，耗时不是模型性能。'}


async def collect(args):
    from evaluation.answer_synthesis import execute
    selected = cases()
    if args.per_category:
        selected = [row for row in selected if row['id'].endswith('-01')]
    if args.limit:
        selected = selected[:args.limit]
    output = Path(args.output)
    previous = {}
    if args.retry_errors:
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if manifest['mode'] != args.mode or manifest['dataset_hash'] != digest(selected):
            raise ValueError('Retry must use the same frozen dataset and mode')
        previous = {row['id']: row for row in read_jsonl(output/'trials.jsonl')}
        write_jsonl(output/'previous-attempts.jsonl', list(previous.values()))
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_jsonl(output/'cases.jsonl', selected)
        manifest = {'mode': args.mode, 'expected_trials': len(selected), 'dataset_hash': digest(selected),
            'timeout_seconds': args.timeout, 'human_labels': 'pending', 'scope': 'main_answer_and_delivery_gate_with_frozen_sources'}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    rows, templates = [], []
    for case in selected:
        started = time.perf_counter()
        if case['id'] in previous and not previous[case['id']].get('error_type'):
            row = previous[case['id']]
        else:
            try:
                row = await asyncio.wait_for(execute(case, args.mode), args.timeout)
            except Exception as error:
                row = {'id': case['id'], 'category': case['category'], 'error_type': type(error).__name__}
            row['duration_ms'] = round((time.perf_counter()-started)*1000, 2)
        rows.append(row);write_jsonl(output/'trials.jsonl', rows)
        templates.append({'id': case['id'], 'assessor': 'human', 'reviewer': None,
            'candidate_hash': digest(row.get('candidate_reply', '')), 'final_hash': digest(row.get('reply', '')),
            'task_completed': None, 'context_coherent': None, 'candidate_correct_units': None,
            'falsely_blocked_units': None, 'specific_facts': None, 'unsupported_specific_facts': None, 'notes': ''})
        write_jsonl(output/'reviews.template.jsonl', templates)
        print(case['id'] + ': ' + row.get('error_type', 'collected'), flush=True)
    summary = summarize(rows, [], len(selected), args.mode)
    manifest['trials_hash'] = digest(rows)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(summary['error_trials'] > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export');export.add_argument('--output', required=True)
    collect_parser = sub.add_parser('collect')
    collect_parser.add_argument('--mode', choices=['replay', 'live'], default='replay')
    collect_parser.add_argument('--output', required=True)
    collect_parser.add_argument('--timeout', type=float, default=120)
    collect_parser.add_argument('--limit', type=int)
    collect_parser.add_argument('--per-category', action='store_true')
    collect_parser.add_argument('--retry-errors', action='store_true')
    score = sub.add_parser('score');score.add_argument('--directory', required=True);score.add_argument('--reviews', required=True)
    args = parser.parse_args()
    if args.command == 'export':
        write_jsonl(Path(args.output), cases());return 0
    if args.command == 'score':
        directory = Path(args.directory)
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if digest(read_jsonl(directory/'cases.jsonl')) != manifest['dataset_hash']:
            raise ValueError('Frozen dataset changed')
        rows = read_jsonl(directory/'trials.jsonl')
        if manifest.get('trials_hash') != digest(rows):
            raise ValueError('Frozen outputs changed')
        result = summarize(rows, read_jsonl(args.reviews), manifest['expected_trials'], manifest['mode'])
        (directory/'reviewed-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2));return 0
    if args.timeout <= 0 or args.limit is not None and args.limit < 1:
        parser.error('timeout and limit must be positive')
    os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
    if args.mode == 'replay':
        os.environ['DEEPSEEK_API_KEY'] = 'offline-replay'
        os.environ['ZHIPUAI_API_KEY'] = 'offline-replay'
        # Enforce zero network calls, including accidentally unmocked providers.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
        from run_agent_offline_guard import install
        install()
    return asyncio.run(collect(args))


if __name__ == '__main__':
    raise SystemExit(main())
