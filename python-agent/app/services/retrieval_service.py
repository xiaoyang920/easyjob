from datetime import timedelta, datetime

from app.clients.es_client import EsVectorStore, EsComponent
from app.services.query_rewrite import ResolvedFilters


class RetrievalService:
    K_RRF = 60
    def __init__(self):
        self._vector_store = EsVectorStore()
        self._article_search = EsComponent()
    async def hybrid_search(
            self,
            semantic_queries: list[str],
            keywords: list[str],
            filters: ResolvedFilters,
            search_mode: str = "hybrid",
            top_k: int = 20,
    )->list[dict]:
        """
        首期实现：手写 RRF 融合当前双索引结果。
        - semantic_queries -> article_vectors KNN
        - keywords -> article BM25
        """
        ranked_lists: list[list[dict]] = []
        vector_filter = self._build_vector_filter(filters)
        if search_mode in ("platform", "hybrid"):
            expanded_keywords = keywords+filters.soft_terms
            for q in semantic_queries:
                hits = await self._vector_store.search(
                    q,
                    top_k=top_k,
                    threshold=0.0,
                    filters=vector_filter,
                )
                ranked_lists.append(self._normalize_vector_hit(h) for h in hits)
            for kw in expanded_keywords:
                hits = await self._article_search.search(
                    kw,
                    page_size=top_k,
                    filters = self._build_keyword_filter(filters),
                )
                ranked_lists.append(self._normalize_keyword_hit(h) for h in hits)
        return self._rrf_merge(ranked_lists, top_k = top_k)

    def _build_vector_filter(self, filters: ResolvedFilters) -> dict:
        """只生成 article_vectors 已存在或已确认补齐的字段。"""
        clauses = []
        if filters.tags:
            clauses.append({"terms": {"tags": filters.tags}})
        if filters.category_ids:
            clauses.append({"terms": {"category_id": filters.category_ids}})
        if filters.author_ids:
            clauses.append({"terms": {"user_id": filters.author_ids}})
        if filters.time_range and filters.time_range != "all":
            clauses.append({"range": {"publish_time": {"gte": self._since(filters.time_range)}}})
        return {"bool": {"filter": clauses}} if clauses else {}

    def _build_article_filter(self, filters: ResolvedFilters) -> dict:
        """article 索引用 camelCase 字段。"""
        clauses = []
        if filters.category_ids:
            clauses.append({"terms": {"categoryId": filters.category_ids}})
        if filters.author_ids:
            clauses.append({"terms": {"userId": filters.author_ids}})
        if filters.time_range and filters.time_range != "all":
            clauses.append({"range": {"publishTime": {"gte": self._since(filters.time_range)}}})
        return {"bool": {"filter": clauses}} if clauses else {}

    @staticmethod
    def _since(time_range: str) -> str:
        delta_map = {
            "today": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
            "year": timedelta(days=365),
        }
        return (datetime.now() - delta_map[time_range]).isoformat()
    @staticmethod
    def _normalize_vector_int(hit: dict)-> dict:
        return {
            **hit,
            "doc_key": f"{hit.get('article_id')}_{hit.get('chunk_index', 0)}",
            "source": "vector",
        }

    @staticmethod
    def _normalize_article_hit(hit: dict) -> dict:
        return {
            "article_id": hit.get("article_id"),
            "title": hit.get("title", ""),
            "content": hit.get("summary", ""),
            "chunk_index": 0,
            "cover_image": hit.get("cover_image", ""),
            "view_count": hit.get("view_count", 0),
            "like_count": hit.get("like_count", 0),
            "user_id": hit.get("user_id"),
            "doc_key": f"article_{hit.get('article_id')}",
            "source": "keyword",
        }

    def _rrf_merge(self, ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
        merged: dict[str, dict] = {}
        for docs in ranked_lists:
            for rank, doc in enumerate(docs, start=1):
                key = doc.get("doc_key") or str(doc.get("article_id"))
                item = merged.setdefault(key, {"doc": doc, "score": 0.0})
                item["score"] += 1.0 / (self.K_RRF + rank)

        out = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        result = []
        for item in out[:top_k]:
            doc = dict(item["doc"])
            doc["score"] = item["score"]
            doc["rrf_score"] = item["score"]
            result.append(doc)
        return result