"""Both RAG retrievers rank the same versioned chunk identities."""
from datetime import timedelta, datetime
import asyncio
import re

from app.clients.es_client import EsVectorStore, EsChunkSearch, ARTICLE_CHUNK_VERSION
from app.services.query_rewrite import ResolvedFilters
from app.config import settings


class RetrievalService:
    K_RRF = 60

    def __init__(self):
        self._vector_store = EsVectorStore()
        self._chunk_search = EsChunkSearch()
        self._slots = asyncio.Semaphore(settings.RETRIEVAL_CONCURRENCY)

    async def hybrid_search(self, semantic_queries: list[str], keywords: list[str],
                            filters: ResolvedFilters, search_mode: str = "hybrid", top_k: int = 20) -> list[dict]:
        calls = []
        chunk_filter = self._build_vector_filter(filters)
        # One semaphore per service, shared by concurrent user requests.
        if not hasattr(self, "_slots"):
            self._slots = asyncio.Semaphore(settings.RETRIEVAL_CONCURRENCY)
        async def retrieve(query, source):
            async with self._slots:
                if source == "vector":
                    call = self._vector_store.search(query, top_k=top_k, threshold=0.0, filters=chunk_filter)
                else:
                    call = self._chunk_search.search(query, page_size=top_k, filters=chunk_filter)
                hits = await asyncio.wait_for(call, settings.RETRIEVAL_TIMEOUT_SECONDS)
            return [doc for hit in hits if (doc := self._normalize_chunk_hit(hit, source)) is not None]
        if search_mode in ("platform", "hybrid"):
            for query in dict.fromkeys(semantic_queries):
                calls.append(retrieve(query, "vector"))
            for keyword in dict.fromkeys([*keywords, *filters.soft_terms]):
                calls.append(retrieve(keyword, "keyword"))
        # Preserve list order, so parallel completion cannot change RRF tie breaks.
        tasks = [asyncio.create_task(call) for call in calls]
        try:
            ranked_lists = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return self._rrf_merge(ranked_lists, top_k)

    def _build_vector_filter(self, filters: ResolvedFilters) -> dict:
        clauses = [{"term": {"chunker_version": ARTICLE_CHUNK_VERSION}}]
        if filters.article_ids:
            clauses.append({"terms": {"article_id": [str(aid) for aid in filters.article_ids]}})
        if filters.tags:
            clauses.append({"terms": {"tags": filters.tags}})
        for tag in filters.required_tags:
            clauses.append({"term": {"tags": tag}})
        if filters.category_ids:
            clauses.append({"terms": {"category_id": filters.category_ids}})
        if filters.author_ids:
            clauses.append({"terms": {"user_id": filters.author_ids}})
        if filters.time_range and filters.time_range != "all":
            clauses.append({"range": {"publish_time": {"gte": self._since(filters.time_range)}}})
        return {"bool": {"filter": clauses}}

    @staticmethod
    def matches_filters(meta: dict, filters: ResolvedFilters) -> bool:
        if filters.author_ids and meta.get('user_id') not in filters.author_ids:
            return False
        if filters.category_ids and meta.get('category_id') not in filters.category_ids:
            return False
        tags = meta.get('current_tags') or []
        if isinstance(tags, str):
            import json
            tags = json.loads(tags)
        if filters.tags and not set(filters.tags).intersection(tags):
            return False
        if not set(filters.required_tags).issubset(tags):
            return False
        if filters.time_range not in (None, 'all'):
            since = datetime.fromisoformat(RetrievalService._since(filters.time_range))
            published = meta.get('publish_time')
            if isinstance(published, str):
                published = datetime.fromisoformat(published)
            if not published or published < since:
                return False
        return True

    @staticmethod
    def _since(time_range: str) -> str:
        delta = {"today": timedelta(days=1), "week": timedelta(days=7),
                 "month": timedelta(days=30), "year": timedelta(days=365)}[time_range]
        return (datetime.now() - delta).isoformat()

    @staticmethod
    def _normalize_chunk_hit(hit: dict, source: str) -> dict | None:
        aid, index = str(hit.get("article_id") or ""), hit.get("chunk_index")
        version, fingerprint = hit.get("chunker_version"), hit.get("source_hash") or ""
        content = hit.get("content") or hit.get("chunk_content") or ""
        if not aid.isdigit() or isinstance(index, bool) or not isinstance(index, int) or index < 0:
            return None
        if version != ARTICLE_CHUNK_VERSION or not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or not content.strip():
            return None
        key = f"{aid}_{version}_{fingerprint}_{index}"
        if hit.get("chunk_id") != key:
            return None
        return {**hit, "article_id": aid, "content": content, "doc_key": key, "source": source}

    def _rrf_merge(self, ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
        merged = {}
        for docs in ranked_lists:
            unique = {}
            for doc in docs:
                if doc["doc_key"] in unique and unique[doc["doc_key"]]["content"] != doc["content"]:
                    raise ConnectionError("同一文本块标识对应不同内容，需要重试")
                unique.setdefault(doc["doc_key"], doc)
            for rank, doc in enumerate(unique.values(), start=1):
                item = merged.setdefault(doc["doc_key"], {"doc": doc, "score": 0.0, "sources": []})
                if item["doc"]["content"] != doc["content"]:
                    raise ConnectionError("文本块在检索期间发生变化，需要重试")
                item["score"] += 1.0 / (self.K_RRF + rank)
                if doc["source"] not in item["sources"]:
                    item["sources"].append(doc["source"])
        result = []
        for item in sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]:
            result.append({**item["doc"], "score": item["score"], "rrf_score": item["score"], "sources": item["sources"]})
        return result
