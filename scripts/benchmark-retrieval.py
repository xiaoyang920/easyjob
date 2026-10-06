"""Real providers, paired serial/parallel recall timings; no generation or rerank."""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python-agent'))
from app.services.retrieval_service import RetrievalService
from app.services.query_rewrite import ResolvedFilters

async def main():
    service = RetrievalService()
    filters = ResolvedFilters()
    queries, keywords = ['Spring Boot 自动配置机制与条件装配', 'Spring Boot 入门 REST 接口'], ['Spring Boot 自动配置', 'Spring Boot REST']
    async def serial():
        lists = []
        f = service._build_vector_filter(filters)
        for q in queries:
            hits = await service._vector_store.search(q, top_k=20, threshold=0.0, filters=f)
            lists.append([v for hit in hits if (v := service._normalize_chunk_hit(hit, 'vector')) is not None])
        for q in keywords:
            hits = await service._chunk_search.search(q, page_size=20, filters=f)
            lists.append([v for hit in hits if (v := service._normalize_chunk_hit(hit, 'keyword')) is not None])
        return service._rrf_merge(lists, 20)
    report = {'scope': '2 vector + 2 keyword recalls; excludes rewriting, rerank, web and generation', 'rounds': []}
    try:
        # Warm transport/model-provider paths before measuring paired runs.
        await service.hybrid_search(queries, keywords, filters)
        for i in range(3):
            samples = {}
            for mode in (['serial', 'parallel'] if i % 2 == 0 else ['parallel', 'serial']):
                start = time.perf_counter()
                results = await (serial() if mode == 'serial' else service.hybrid_search(queries, keywords, filters))
                samples[mode] = {'ms': round((time.perf_counter()-start)*1000, 2), 'ids': [v['doc_key'] for v in results]}
            report['rounds'].append({'serial_ms': samples['serial']['ms'], 'parallel_ms': samples['parallel']['ms'],
                                     'same_order': samples['serial']['ids'] == samples['parallel']['ids'], 'results': len(samples['parallel']['ids'])})
        report['serial_median_ms'] = statistics.median(r['serial_ms'] for r in report['rounds'])
        report['parallel_median_ms'] = statistics.median(r['parallel_ms'] for r in report['rounds'])
        report['median_reduction_pct'] = round((1-report['parallel_median_ms']/report['serial_median_ms'])*100, 1)
    finally:
        await service._vector_store.client.close()
        await service._chunk_search.client.close()
    (ROOT/'logs/optimization-rag-benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

asyncio.run(main())
