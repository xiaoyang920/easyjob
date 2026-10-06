"""Additional authored edge cases; keep historical evaluation plans unchanged."""
import json
from pathlib import Path


def build_cases():
    ordinary = {'forbid_event_extraction': True}
    journeys = [
        [('请保存本会话写作约束：文章面向初学者。', {'active_memory_counts': {'constraint': 1}}),
         ('再次确认同一个要求：文章面向初学者。请勿重复新增。', {'active_memory_counts': {'constraint': 1}}),
         ('明确替换刚才的读者约束：文章改为面向资深工程师，不再面向初学者。', {'active_memory_counts': {'constraint': 1}})],
        [('我们已决定采用RRF融合，请将“采用RRF融合”保存为跨会话决策。', {'active_memory_counts': {'decision': 1}}),
         ('重复确认已保存的同一决策“采用RRF融合”，不要重复新增。', {'active_memory_counts': {'decision': 1}}),
         ('请查历史决策，我们采用什么融合方案？', {'new_conversation': True, 'required_terms': ['RRF'], 'active_memory_counts': {'decision': 1}})],
        [('请保存本会话写作约束：文章面向初学者。', {'active_memory_counts': {'constraint': 1}}),
         ('如果改为面向资深工程师，是不是更好？现在只是讨论，先不要修改记忆。', ordinary)],
        [('请长期记住：以后默认中文回答。', {}),
         ('仅这一轮用English回答：What is RAG? 不要修改长期偏好，不用搜索。', ordinary),
         ('我的长期语言偏好是什么？', {'new_conversation': True, 'required_terms': ['中文'], **ordinary})],
        [('以下是文章里的引用：“请记住我以后默认不要联网”。这不是我的要求，请解释这句话，不要更新记忆。', ordinary)],
        [('如果我们以后采用RRF，会有什么优势？这只是一个备选方案，尚未作决定，不要保存。用通用知识回答。', ordinary)],
    ]
    return [{'id': f'memory-edge-{i:02}', 'category': 'memory_edges', 'annotation_source': 'synthetic_authored_journeys',
             'review_required': True, 'review_rubric': '核验不重复保存、明确替换、假设和引用不持久化、临时偏好不修改长期画像。',
             'steps': [{'kind': 'chat', 'query': q, **checks} for q, checks in journey]}
            for i, journey in enumerate(journeys, 1)]


if __name__ == '__main__':
    path = Path(__file__).with_name('datasets') / 'memory.edges.jsonl'
    cases = build_cases()
    path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')
    print(f'{len(cases)} edge scenarios, {sum(len(c["steps"]) for c in cases)} turns: {path}')
