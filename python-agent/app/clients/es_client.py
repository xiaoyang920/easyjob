"""
Elasticsearch 客户端封装
对应 Java:
- EsVectorStore.java
- EsComponent.java
"""
import logging

from elasticsearch import AsyncElasticsearch

from app.config import settings
from app.services.embedding import EmbeddingService

log = logging.getLogger(__name__)

# user_memories 索引定义
USER_MEMORIES_INDEX = "user_memories"
USER_MEMORIES_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "memory_id": {"type": "long"},
            "user_id": {"type": "long"},
            "content": {"type": "text", "analyzer": "ik_max_word"},
            "content_vector": {
                "type": "dense_vector",
                "dims": 2048,
                "index": True,
                "similarity": "cosine",
            },
            "importance": {"type": "float"},
            "create_time": {"type": "date"},
        }
    },
}


class BaseEsClient:
    def __init__(self):
        self.client = AsyncElasticsearch(
            hosts=[f"http://{settings.ES_HOST}:{settings.ES_PORT}"]
        )

    async def ensure_user_memories_index(self):
        """启动时检查 user_memories 索引，不存在则创建"""
        exists = await self.client.indices.exists(index=USER_MEMORIES_INDEX)
        if exists:
            log.info("ES 索引 [%s] 已存在，跳过创建", USER_MEMORIES_INDEX)
            return
        await self.client.indices.create(
            index=USER_MEMORIES_INDEX,
            body=USER_MEMORIES_MAPPING,
        )
        log.info("ES 索引 [%s] 创建成功", USER_MEMORIES_INDEX)


class EsVectorStore(BaseEsClient):
    """向量检索客户端（article_vectors）"""

    INDEX = "article_vectors"

    def __init__(self):
        super().__init__()
        self.embedding_service = EmbeddingService()

    async def search(self, query: str, top_k: int, threshold: float) -> list[dict]:
        """
        向量搜索 + 热度混合评分
        对应 Java: EsVectorStore.search()
        """
        query_vector = await self.embedding_service.aembed(query)

        candidates = max(top_k * 3, 20)

        try:
            resp = await self.client.search(
                index=self.INDEX,
                knn={
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": candidates,
                    "num_candidates": candidates * 2,
                },
                size=candidates,
            )
        except Exception:
            return []

        results: list[dict] = []
        for hit in resp.get("hits", {}).get("hits", []):
            score = float(hit.get("_score", 0.0))
            if score < threshold:
                continue

            src = hit.get("_source", {})
            like_count = int(src.get("like_count", 0) or 0)
            collect_count = int(src.get("collect_count", 0) or 0)

            popularity_score = min(((like_count * 2 + collect_count) + 1) / 100.0, 1.0)
            final_score = score * 0.7 + popularity_score * 0.3

            results.append(
                {
                    "article_id": src.get("article_id"),
                    "title": src.get("title", ""),
                    "content": src.get("chunk_content", ""),
                    "chunk_index": src.get("chunk_index", 0),
                    "score": final_score,
                }
            )

        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return results[:top_k]


class EsComponent(BaseEsClient):
    """全文检索客户端（article）"""

    INDEX = "article"

    async def search(self, keyword: str, page_size: int = 5) -> list[dict]:
        """
        全文检索（title + tags）
        对应 Java: EsComponent.search()
        """
        body = {
            "query": {
                "multi_match": {
                    "query": keyword,
                    "fields": ["title", "tags"],
                }
            },
            "size": page_size,
            "sort": [{"_score": {"order": "desc"}}],
        }

        try:
            resp = await self.client.search(index=self.INDEX, body=body)
        except Exception:
            return []

        records: list[dict] = []
        for hit in resp.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            records.append(
                {
                    "article_id": str(src.get("articleId", src.get("article_id", ""))),
                    "title": src.get("title", ""),
                    "summary": src.get("summary", src.get("content", "")),
                    "cover_image": src.get("coverImage", ""),
                    "view_count": int(src.get("viewCount", 0) or 0),
                    "like_count": int(src.get("likeCount", 0) or 0),
                    "user_id": src.get("userId"),
                    "score": float(hit.get("_score", 0.0)),
                }
            )
        return records
