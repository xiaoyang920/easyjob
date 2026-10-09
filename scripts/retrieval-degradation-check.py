"""Real local retrieval/LLM verification with controlled read-only failures."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.clients.mysql_client import db
from app.graph.nodes import search_worker as search
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.graph.staged_plan import ExecutionTask
from app.graph.staged_runtime import task_context, task_result
from app.utils.snowflake import SnowflakeGenerator
from app.services.dependency_policy import DependencyPolicy


async def main():
    if db.url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('Local retrieval only')
    report = {'checks': [], 'scope': 'actual local public corpus, SQL/ES, query rewrite and integrated Main assessment; injected reranker failures, no separate relevance model'}
    output = ROOT / 'logs/evaluation' / f'retrieval-degradation-{datetime.now():%Y%m%d-%H%M%S}.json'
    uid = SnowflakeGenerator(worker_id=31).next_id()
    # This is a labeled positive question in the existing sample corpus.
    query = '只搜索作者“RAG评测样例”的平台文章：Redis 热点键过期导致缓存击穿如何解决？请基于资料回答，不要联网。'
    await db.connect()
    try:
        for name, goal, invalid_response in (
                ('main_selects_relevant_fallback', query, False),
                ('main_rejects_unrelated_fallback', '只搜索作者“RAG评测样例”的平台文章：有没有量子香蕉数据库的部署教程？不要联网。', False),
                ('malformed_rerank_response_is_marked_degraded', query, True)):
            initial = create_initial_state(uid, goal, [])
            state = task_context(initial, ExecutionTask(task_id='check', kind='search', actor='main', instruction=goal, allow_web=False))
            faulty = AsyncMock(side_effect=TimeoutError('injected rerank outage'))
            if invalid_response:
                faulty = AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None,
                    json=lambda: {'output': {'results': [{'index': 0, 'relevance_score': float('nan')}]}}))
            # Each case must exercise its own injected response, independently of earlier outages.
            with patch('app.services.reranker.rerank_policy', DependencyPolicy('test reranker', attempts=1)), patch.object(search.reranker_service.client, 'post', faulty):
                result = await search.retrieve_evidence(state)
            if not faulty.await_count:
                raise AssertionError(f'{name}: injected reranker was not exercised')
            degraded = result['retrieval_report']['platform'].get('rerank', {}).get('status') == 'degraded'
            initial['task_results'] = {'check': task_result(state, {
                'worker_results': [{'worker_name': 'search', 'status': result['status'],
                    'result': result.get('rag_context') or result.get('result')}],
                'citations': result['citations'], 'article_cards': result['article_cards'],
                'retrieval_report': result['retrieval_report']}, raw_retrieval=True)}
            next_action = await main_agent.decide_main_action(initial)
            assessment = next_action.get('main_decision', {}).get('evidence_assessment') or {}
            if name == 'main_rejects_unrelated_fallback':
                passed = assessment.get('adequacy') == 'none' and not assessment.get('selected_ids')
            else:
                passed = (degraded and result['status'] == 'succeeded'
                          and assessment.get('adequacy') in ('partial', 'sufficient')
                          and bool(assessment.get('selected_ids')))
            value = {'name': name, 'passed': bool(passed), 'status': result['status'], 'citation_count': len(result['citations']),
                     'reranker_calls': faulty.await_count, 'retrieval_report': result['retrieval_report'],
                     'main_action': next_action['main_action'], 'evidence_assessment': assessment}
            report['checks'].append(value)
            print(json.dumps(value, ensure_ascii=False), flush=True)
            if not passed: raise AssertionError(name)
    finally:
        await db.disconnect()
        await search.reranker_service.client.aclose()
        await search.retrieval_service_instance._vector_store.client.close()
        await search.retrieval_service_instance._chunk_search.client.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(str(output), flush=True)


if __name__ == '__main__': asyncio.run(main())
