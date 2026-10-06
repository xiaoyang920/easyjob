"""Real first-decision regression for background vs temporary response requests.

No user records, graph runs or memory writes. Invokes the configured LLM explicitly.
"""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.config import get_llm, settings
from app.graph.main_agent import MainDecision, MAIN_PROMPT, build_main_messages
from app.graph.state_factory import create_initial_state
from app.models.memory_change import validate_memory_changes


CASES = [
    ('background_with_request', '我是个新手你给我解释详细', ['experience'], ['新手'], ''),
    ('background_paraphrase', '我刚开始学编程，麻烦从基础讲讲缓存是什么', ['experience'], ['编程'], ''),
    ('topic_beginner', '我是Redis新手，给我解释缓存是什么', ['experience'], ['Redis', 'Java', '三年'], 'Java开发三年'),
    ('temporary_detail', '这次请讲详细一点，让新手也能看懂缓存是什么', [], [], ''),
    ('hypothetical', '假设我是个新手，你会怎么解释缓存？', [], [], ''),
    ('third_party', '我的同事是新手，请帮我写一段解释缓存的话给他', [], [], ''),
    ('opt_out', '我是新手，详细解释缓存，但不要把这句话保存到长期记忆', [], [], ''),
    ('durable_detail', '以后回答都请讲详细一点，用中文。现在解释缓存是什么',
     ['preferences.detail', 'preferences.language'], [], ''),
]


async def main(repeats):
    model = get_llm(temperature=0, max_retries=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS)
    control = model.with_structured_output(MainDecision, method='function_calling')
    gate = asyncio.Semaphore(2)
    rows = []

    async def trial(case, repetition):
        name, query, keys, terms, experience = case
        state = create_initial_state(0, query, [])
        state['user_profile'] = {'topics': ['Redis', 'Java', 'Agent'],
                                'experience': experience or 'unknown', 'preferences': {'code_language': 'Java'}}
        state['history_messages'] = [{'role': 'assistant', 'content': '你想了解缓存的哪部分？'}]
        row = {'case': name, 'repetition': repetition, 'query': query, 'expected_keys': keys}
        try:
            async with gate:
                decision = await asyncio.wait_for(control.ainvoke(build_main_messages(state)), 60)
            validate_memory_changes(state, decision.memory_changes)
            changes = [c.model_dump() for c in decision.memory_changes]
            actual = sorted(c['key'] for c in changes)
            values = ' '.join(str(c['value']) for c in changes if c['key'] == 'experience')
            passed = (decision.action == 'answer' and actual == sorted(keys)
                      and all(c['kind'] == 'profile' and c['scope'] == 'user' for c in changes)
                      and all(t.lower() in values.lower() for t in terms))
            row.update(passed=passed, action=decision.action, changes=changes,
                       reply=decision.reply)
        except Exception as exc:
            row.update(passed=False, error_type=type(exc).__name__)
        rows.append(row)
        print(json.dumps({k: row[k] for k in ('case', 'repetition', 'passed')}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(trial(case, n) for case in CASES for n in range(1, repeats + 1)))
    report = {'scope': 'real first Main decision; no database writes; authored boundary cases',
              'model': model.model_name, 'temperature': 0, 'repeats': repeats,
              'prompt_sha256': hashlib.sha256(MAIN_PROMPT.encode()).hexdigest(),
              'cases_sha256': hashlib.sha256(json.dumps(CASES, ensure_ascii=False).encode()).hexdigest(),
              'passed': sum(r['passed'] for r in rows), 'total': len(rows),
              'results': sorted(rows, key=lambda r: (r['case'], r['repetition']))}
    output = ROOT / 'logs/evaluation' / f'memory-background-{datetime.now():%Y%m%d-%H%M%S}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'total': report['total'], 'report': str(output)}, ensure_ascii=False))
    if report['passed'] != report['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=2, choices=range(1, 6))
    asyncio.run(main(parser.parse_args().repeats))
