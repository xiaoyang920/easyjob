"""Small real-model check of blog profile semantics; no persistence or user data."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.config import get_llm, settings
from app.graph.main_agent import MainDecision, build_main_messages
from app.graph.state_factory import create_initial_state
from app.models.memory_change import validate_memory_changes

async def main():
    cases = [
        ('我长期关注Java、Redis和Agent，以后给我推荐这些方向的文章。', 'topics'),
        ('我是Python新手，讲Python的时候给我解释详细。', 'experience'),
        ('请解释一下Redis缓存穿透，这次用Java代码举例。', None),
        ('记住我也长期关注分布式系统。', 'topics'),
    ]
    results = []
    model = get_llm(temperature=0, max_tokens=settings.MAIN_OUTPUT_MAX_TOKENS).with_structured_output(MainDecision, method='function_calling')
    for query, expected in cases:
        state = create_initial_state(7, query, [])
        state['user_profile'] = {'topics': ['Java', 'Redis', 'Agent'], 'experience': 'unknown', 'preferences': {'code_language': 'Java'}} if '也长期' in query else {}
        decision = MainDecision.model_validate(await asyncio.wait_for(model.ainvoke(build_main_messages(state)), 60))
        validate_memory_changes(state, decision.memory_changes)
        changes = {c.key: c.value for c in decision.memory_changes}
        if expected:
            assert expected in changes, (query, changes)
            if expected == 'topics':
                required = {'Java', 'Redis', 'Agent', '分布式系统'} if '也长期' in query else {'Java', 'Redis', 'Agent'}
                assert required <= set(changes['topics']), changes
            else:
                assert 'Python' in changes['experience'] and '新手' in changes['experience'], changes
                assert 'topics' not in changes, changes
        else:
            assert not changes, changes
        results.append({'query': query, 'changes': changes, 'passed': True})
    output = ROOT / 'logs/profile-topics-model-check.json'
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(results)} real model checks passed; details in {output.name}')

if __name__ == '__main__': asyncio.run(main())
