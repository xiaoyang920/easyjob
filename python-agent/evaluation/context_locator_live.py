"""Real Main choices for multi-keyword, chapter and cursor readers; synthetic data."""
import argparse
import asyncio
from pathlib import Path
from unittest.mock import patch

from app.graph import main_agent
from evaluation.context_live import Evaluation, deny, parse_json


def source(text):
    return {'status': 'succeeded', 'kind': 'search', 'actor': 'main', 'retrieval_target': 'knowledge',
        'instruction': '合成定位验收资料', 'result': text, 'citations': [
            {'id': 'source:1', 'title': '合成定位资料', 'contentScope': 'fixture_text'}],
        'citation_contents': {'source:1': text}, 'article_cards': []}


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    evaluation = Evaluation(output)
    many = 'padding ' * 14000 + '\n首轮口令：FIRST-K8P2\n' + 'other ' * 7000 + '\n复核口令：SECOND-Q9R3'
    chapters = '# Overview\n' + 'padding ' * 14000 + '\n# Target\n章节代号：CHAPTER-K8P2\n# Other\n' + 'other ' * 3000
    records = ''.join(f'needle 条目{i+1} 代号=CODE-{i}-K8P2\n' + 'padding ' * 600 for i in range(10))
    cases = [
        ('multi', '从source读取“首轮口令”和“复核口令”，请一次用read_task_result的queries传入这两个关键词。'
         '只返回JSON：first、second分别填两个口令。不联网、不重新检索或写记忆。', many,
         {'first': 'FIRST-K8P2', 'second': 'SECOND-Q9R3'}),
        ('section', '从source目录找到Target章节，用section_id读取该章节。只返回JSON：code填章节代号。'
         '不联网、不重新检索或写记忆。', chapters, {'code': 'CHAPTER-K8P2'}),
        ('cursor', '从source找第10条needle的代号。读取只用query=needle、max_chars=1500；'
         '沿next_cursor继续，保持query与max_chars，不猜start_char，不改搜索词，不联网或写记忆。'
         '只返回JSON：code填第10条的代号。', records, {'code': 'CODE-9-K8P2'}),
    ]
    with patch.object(main_agent.memory_policy_service, 'enqueue_changes', deny):
        for repeat in range(2):
            for name, query, text, expected in cases:
                result, row = await evaluation.turn(f'locator_{name}_{repeat+1}', query, results={'source': source(text)})
                args = [task.get('tool_args') or {} for action in (result or {}).get('action_history', [])
                        for task in action.get('tasks') or []]
                feature = {'multi': 'queries', 'section': 'section_id', 'cursor': 'cursor'}[name]
                evaluation.check(row, exact_values=parse_json(row['reply']) == expected,
                    requested_locator_used=any(value.get(feature) for value in args),
                    real_provider_usage=row['metrics']['measured_llm_calls'] > 0)
    evaluation.save()
    print({'cases': len(evaluation.rows), 'passed': sum(row['passed'] for row in evaluation.rows)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))
