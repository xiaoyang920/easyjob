"""No-I/O context preparation benchmark with a frozen source manifest."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time
import tracemalloc
from unittest.mock import patch

from app.config import settings
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.services.context_projection import context_breakdown
from app.utils.context_budget import ensure_request_budget

ROOT = Path(__file__).resolve().parents[2]
FILES = ('app/graph/main_agent.py', 'app/models/main_tool.py', 'app/graph/staged_plan.py',
         'app/services/result_access.py', 'app/services/context_projection.py',
         'app/services/context_tools.py', 'app/services/main_context.py',
         'app/services/run_metrics.py', 'app/utils/context_budget.py', 'app/utils/token_utils.py')


def fixture(size):
    state = create_initial_state(7, '检查已有资料，不联网，不修改数据。', [
        {'role': 'user', 'content': '仅用于当前任务；不要自动保存记忆。'},
        {'role': 'assistant', 'content': '已记录当前要求。'}])
    state['task_results'] = {f'log_{i}': {
        'status': 'succeeded', 'kind': 'search', 'actor': 'main', 'retrieval_target': 'knowledge',
        'instruction': '合成日志', 'result': word * size + '\n现场校验代号：TEST-Q8R2',
        'citations': [], 'article_cards': []} for i, word in enumerate(('alpha ', 'beta ', 'gamma '))}
    state['action_task_ids'] = ['log_2']
    return state


def build(state):
    render = main_agent.main_message_renderer(state, {})
    messages = render(state['history_messages'])
    tokens = ensure_request_budget(messages, [main_agent.MainDecision])
    context_breakdown(messages, [main_agent.MainDecision])
    render([])  # Same preparation's dry admission / summary render.
    return tokens


def run(output, repeats):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for relative in FILES:
        source = ROOT / 'python-agent' / relative
        content = source.read_bytes()
        target = output / 'frozen' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest[relative] = hashlib.sha256(content).hexdigest()
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    report = {'real_provider_calls': False, 'git_head': head, 'source_sha256': manifest,
              'model': settings.DEEPSEEK_MODEL, 'repeats': repeats, 'rows': []}
    modes = [False, True] if hasattr(settings, 'CONTEXT_BUILD_CACHE_ENABLED') else [None]
    for size in (2000, 14000, 40000):
        state = fixture(size)
        times = {mode: [] for mode in modes}
        tokens = {}
        for repeat in range(repeats):
            for mode in modes if repeat % 2 == 0 else list(reversed(modes)):
                with ExitStack() as stack:
                    if mode is not None:
                        stack.enter_context(patch.object(settings, 'CONTEXT_BUILD_CACHE_ENABLED', mode))
                    started = time.perf_counter()
                    tokens[mode] = build(state)
                    times[mode].append((time.perf_counter() - started) * 1000)
        for mode in modes:
            with ExitStack() as stack:
                if mode is not None:
                    stack.enter_context(patch.object(settings, 'CONTEXT_BUILD_CACHE_ENABLED', mode))
                tracemalloc.start()
                build(state)
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
            values = sorted(times[mode])
            report['rows'].append({'size': size, 'cache': mode, 'median_ms': statistics.median(values),
                'p90_ms': values[min(len(values)-1, int(len(values)*.9))], 'peak_bytes': peak,
                'request_tokens': tokens[mode]})
        assert len(set(tokens.values())) == 1, 'Cache changed the request budget'
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'source_sha256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', default=30, type=int)
    args = parser.parse_args()
    run(args.output.resolve(), max(1, args.repeats))
