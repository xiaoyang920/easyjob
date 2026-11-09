"""Inject a wrong initial source choice, then run the real model's scoped recheck.

Only synthetic documents are sent. No user rows, conversation or checkpoint writes.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
from app.services import grounding
from app.services.execution_facts import execution_facts
from app.services.run_metrics import RunMetrics
from langchain_core.runnables import RunnableLambda


async def trial(original_supported):
    sources = [{'id': 'smoke:1', 'title': '测试资料A', 'content':
                '演示环境内存为12GB。' if original_supported else '本资料只记录演示环境超时为30秒。'},
               {'id': 'smoke:2', 'title': '测试资料B', 'content': '演示环境内存为12GB。'}]
    text = '演示环境内存为12GB。[smoke:1]'
    catalog = grounding.evidence_catalog(sources)
    initial = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
        grounding.ClaimReview(unit_index=0, verdict='supported', evidence_ids=[
            key for key, quote in catalog.items() if quote.citation_id == 'smoke:2' and quote.field == 'content'])])])
    first = SimpleNamespace(ainvoke=AsyncMock(return_value=initial))
    get_real_model = grounding.get_llm
    selections = 0

    def model(**kwargs):
        nonlocal selections
        selections += 1
        if selections == 1:
            return SimpleNamespace(with_structured_output=lambda *args, **kw: first)
        return get_real_model(**kwargs)

    meter = RunMetrics()

    async def run(_):
        with patch.object(grounding, 'get_llm', side_effect=model):
            return await grounding.review_text(text, sources, execution_facts({}))

    review = await RunnableLambda(run).ainvoke({}, config={'callbacks': [meter]})
    record = review.contract_audit['citation_rechecks'][0]
    assert review.contract_audit['citation_recheck_calls'] == 1
    assert record['outcome'] == ('matched' if original_supported else 'not_supported'), record['outcome']
    assert bool(review) != original_supported
    assert meter.snapshot()['llm_calls'] == 1
    return {'case': 'original_supported' if original_supported else 'original_missing_support',
            'outcome': record['outcome'], 'real_model_calls': meter.snapshot()['llm_calls'],
            'review_calls_including_injected': review.contract_audit['model_calls']}


async def main():
    results = []
    for supported in (True, False):
        result = await trial(supported)
        results.append(result)
        print(json.dumps(result), flush=True)
    print(json.dumps({'passed': len(results), 'real_model_calls': 2, 'database_writes': 0}), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Citation smoke failed: ' + type(error).__name__, flush=True)
        raise SystemExit(1)
