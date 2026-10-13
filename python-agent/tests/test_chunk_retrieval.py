from rpc_fakes import public_reader
"""Chunk corpus, public version verification and evidence assembly without network access."""
import os
os.environ["DEEPSEEK_API_KEY"] = "offline-test"
os.environ["AGENT_SERVICE_KEY"] = "offline-service-key-32-bytes-long!!"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from datetime import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.clients.es_client import EsChunkSearch, EsVectorStore
from app.services.retrieval_service import RetrievalService
from app.services.query_rewrite import ResolvedFilters
from app.services.reranker import RerankerService
from app.services.citation_builder import CitationBuilder
from app.graph.nodes import search_worker
from fakes import article_chunk


class ChunkRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_chunk_gets_two_votes_and_distinct_chunks_are_not_article_deduplicated(self):
        a, b = article_chunk(index=0), article_chunk(index=1, content="second paragraph")
        service = RetrievalService.__new__(RetrievalService)
        service._vector_store = SimpleNamespace(search=AsyncMock(return_value=[a, a, b]))
        service._chunk_search = SimpleNamespace(search=AsyncMock(return_value=[b, a]))
        result = await service.hybrid_search(["query", "query"], ["query"], ResolvedFilters(soft_terms=["query"]))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["rrf_score"], 1 / 61 + 1 / 62)
        self.assertEqual(result[1]["rrf_score"], 1 / 62 + 1 / 61)
        self.assertEqual(result[0]["sources"], ["vector", "keyword"])
        self.assertEqual(service._vector_store.search.await_count, 1)
        self.assertEqual(service._chunk_search.search.await_count, 1)
        self.assertEqual(service._vector_store.search.call_args.kwargs["filters"],
                         service._chunk_search.search.call_args.kwargs["filters"])

    async def test_knn_and_bm25_query_the_same_corpus_with_author_category_date_and_tag_filters(self):
        service = RetrievalService.__new__(RetrievalService)
        filters = service._build_vector_filter(ResolvedFilters(tags=["Java"], author_ids=[7], category_ids=[2], time_range="week"))
        client = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": []}}))
        vector = EsVectorStore.__new__(EsVectorStore)
        vector.client, vector.embedding_service = client, SimpleNamespace(aembed=AsyncMock(return_value=[0.1]))
        lexical = EsChunkSearch.__new__(EsChunkSearch)
        lexical.client = client
        await vector.search("query", 20, 0, filters)
        vector_call = client.search.call_args.kwargs
        await lexical.search("query", 20, filters)
        keyword_call = client.search.call_args.kwargs
        self.assertEqual(vector_call["index"], keyword_call["index"])
        self.assertEqual(keyword_call["index"], "article_vectors")
        self.assertEqual(vector_call["knn"]["filter"], keyword_call["body"]["query"]["bool"]["filter"][0])
        self.assertIn("chunk_content^3", keyword_call["body"]["query"]["bool"]["must"][0]["multi_match"]["fields"])
        self.assertEqual(filters["bool"]["filter"][0], {"term": {"chunker_version": "html-dom-v1"}})
        self.assertIn({"terms": {"category_id": [2]}}, filters["bool"]["filter"])

    async def test_old_versions_and_invalid_identifiers_never_enter_fusion(self):
        valid = article_chunk()
        for invalid in ({**valid, "chunker_version": "legacy"}, {**valid, "chunk_id": "42_0"},
                        {**valid, "chunk_index": True}, {**valid, "source_hash": ""}, {**valid, "content": " "}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(RetrievalService._normalize_chunk_hit(invalid, "vector"))
        a = RetrievalService._normalize_chunk_hit(valid, "vector")
        b = {**a, "content": "conflicting snapshot"}
        with self.assertRaises(ConnectionError):
            RetrievalService.__new__(RetrievalService)._rrf_merge([[a, b]], 20)

    async def test_public_source_recheck_retains_chunk_body_and_rejects_stale_versions_and_metadata(self):
        html = "<h2>Code</h2><pre>    run();\n</pre><p>Another paragraph</p>"
        now = datetime(2026, 10, 1, 12, 0, 0)
        chunk = article_chunk(index=3, html=html, content="```java\n    run();\n```", section_path=["RAG", "Code"],
                              user_id=7, category_id=2, publish_time=now.isoformat(), tags=["Java"])
        row = SimpleNamespace(_mapping={"article_id": 42, "title": "RAG", "content": html, "user_id": 7,
                                       "category_id": 2, "publish_time": now, "current_tags": '["Java"]'})
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[row]))
        stale = article_chunk(html="<p>old</p>", user_id=7, category_id=2, publish_time=now.isoformat(), tags=["Java"])
        candidates = [chunk, chunk, stale, article_chunk(aid="99"), {**chunk, "title": "old title"},
                      {**chunk, "category_id": 8}, {**chunk, "tags": ["Old"]}, {**chunk, "publish_time": "2025-01-01T00:00:00"}]
        with patch.object(search_worker, "public_read", public_reader(database)):
            result = await search_worker._verify_candidates_from_mysql(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], chunk["content"])
        self.assertEqual(result[0]["chunk_index"], 3)
        self.assertEqual(result[0]["section_path"], ["RAG", "Code"])
        self.assertEqual("published", database.fetch_all.call_args.args[0])

    async def test_reranker_failure_still_limits_each_article_and_keeps_alternatives(self):
        ranker = RerankerService.__new__(RerankerService)
        ranker.client = SimpleNamespace(post=AsyncMock(side_effect=TimeoutError("offline")))
        candidates = [article_chunk(index=i, score=1 - i / 100) for i in range(6)] + [article_chunk(aid="43", score=0.1)]
        result = await ranker.rerank("query", candidates)
        self.assertEqual([doc["article_id"] for doc in result], ["42", "42", "42", "43"])
        self.assertTrue(all(doc["rerank_status"] == "degraded" for doc in result))
        self.assertEqual(len(search_worker._build_cards_from_results(result)), 2)

    async def test_invalid_provider_scores_are_degraded_candidates_not_accepted_relevance(self):
        ranker = RerankerService.__new__(RerankerService)
        candidates = [article_chunk()]
        for score in (float('nan'), float('inf'), True, '0.9', -1, 1.1):
            ranker.client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {'output': {'results': [{'index': 0, 'relevance_score': score}]}})))
            with self.subTest(score=score):
                result = await ranker.rerank('query', candidates)
                self.assertTrue(all(d['rerank_status'] == 'degraded' for d in result))

    async def test_real_client_normalization_fusion_verification_rerank_and_citations_share_the_chunk(self):
        html = "<pre>" + "    run();\n" * 150 + "</pre>"
        content = "```java\n" + "    run();\n" * 150 + "```"
        chunk = article_chunk(html=html, content=content, index=5, section_path=["RAG", "Code"])
        es_source = {**chunk, "chunk_content": content}
        es_source.pop("content")
        es = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": [{"_source": es_source, "_score": 0.8}]}}))
        vector = EsVectorStore.__new__(EsVectorStore)
        vector.client, vector.embedding_service = es, SimpleNamespace(aembed=AsyncMock(return_value=[0.1]))
        keyword = EsChunkSearch.__new__(EsChunkSearch)
        keyword.client = es
        service = RetrievalService.__new__(RetrievalService)
        service._vector_store, service._chunk_search = vector, keyword
        fused = await service.hybrid_search(["query"], ["query"], ResolvedFilters())
        self.assertAlmostEqual(fused[0]["rrf_score"], 2 / 61)
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[SimpleNamespace(_mapping={"article_id": 42, "title": "RAG", "content": html})]))
        with patch.object(search_worker, "public_read", public_reader(database)):
            verified = await search_worker._verify_candidates_from_mysql(fused)
        ranker = RerankerService.__new__(RerankerService)
        ranker.client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"output": {"results": [{"index": 0, "relevance_score": 0.9}]}})))
        ranked = await ranker.rerank("query", verified)
        citations, context = CitationBuilder().build(ranked, id_prefix="main:")
        self.assertEqual(citations[0].id, "main:1")
        self.assertEqual(citations[0].chunkId, chunk["chunk_id"])
        self.assertEqual(citations[0].chunkIndex, 5)
        self.assertEqual(citations[0].sourceHash, chunk["source_hash"])
        self.assertEqual(len(citations[0].excerpt), 1200)
        self.assertIn(content, context)
        self.assertTrue(context.endswith("```"))
        self.assertIn("RAG > Code", ranker.client.post.call_args.kwargs["json"]["input"]["documents"][0])
