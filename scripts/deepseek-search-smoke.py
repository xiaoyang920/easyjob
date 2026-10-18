"""Opt-in real Search / Fetch check using only fixed public queries and pages.

Run with python-agent/.venv/Scripts/python.exe scripts/deepseek-search-smoke.py --live.
Never records credentials, private prompts, page contents or raw provider errors.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))


async def main():
    from app.tools.web_search import do_search, do_fetch, WebSearchError, _client
    from app.services.grounding import source_contents
    report = {'provider': 'deepseek', 'checks': {}, 'live_model_calls': 0,
              'query': 'Spring Boot REST service guide site:spring.io'}
    try:
        start = perf_counter()
        results = await do_search(report['query'], size=3)
        report['search_ms'] = round((perf_counter() - start) * 1000)
        assert results, 'Search returned no usable public evidence'
        report['checks']['search_returns_public_results'] = True
        report['results'] = [{'title': item['title'], 'url': item['url'], 'scope': item['contentScope'],
                              'chars': len(item['content']), 'fetch_status': item['fetchStatus']} for item in results]
        page = await do_fetch('https://api-docs.deepseek.com/zh-cn/guides/search/')
        assert page['content'] and page['contentScope'] in ('page_content', 'page_excerpt')
        report['checks']['fetch_returns_page_body'] = True
        report['fetch_scope'] = page['contentScope']
        citations = [{'id': f'live:web{i}', 'excerpt': item['content'][:1200], 'contentScope': item['contentScope']}
                     for i, item in enumerate(results)]
        state = {'task_results': {'live': {'status': 'succeeded',
                  'citation_contents': {citation['id']: item['content'] for citation, item in zip(citations, results)}}}}
        sources = source_contents(state, citations)
        assert [s['content'] for s in sources] == [r['content'] for r in results]
        report['checks']['verifier_receives_original_selected_contents'] = True
        report['status'] = 'passed'
    except WebSearchError as exc:
        report.update(status='failed', error=str(exc))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
    finally:
        await _client.aclose()
        target = ROOT / 'logs/deepseek-search-smoke.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Allow a few billed public Search / Fetch calls')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required')
    raise SystemExit(0 if asyncio.run(main()) else 1)
