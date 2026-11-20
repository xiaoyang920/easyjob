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
ARTICLE_CHUNK_VERSION = "html-dom-v1"
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
            "memory_type": {"type": "keyword"},
            "scope": {"type": "keyword"},
            "scope_conversation_id": {"type": "long"},
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
            await self.client.indices.put_mapping(index=USER_MEMORIES_INDEX, properties={
                name: USER_MEMORIES_MAPPING["mappings"]["properties"][name]
                for name in ("memory_type", "scope", "scope_conversation_id")})
            log.info("ES 索引 [%s] 已存在，补充记忆范围字段", USER_MEMORIES_INDEX)
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

    async def search(self, query: str, top_k: int, threshold: float, filters: dict | None = None) -> list[dict]:
        """
        KNN 相似度排序；RRF 只融合名次，不叠加热度分。
        """
        query_vector = await self.embedding_service.aembed(query)

        candidates = max(top_k * 3, 20)

        knn = {
            "field": "content_vector",
            "query_vector": query_vector,
            "k": candidates,
            "num_candidates": candidates * 2,
        }
        if filters:
            knn["filter"] = filters
        resp = await self.client.search(
            index=self.INDEX,
            knn=knn,
            size=candidates,
        )

        results: list[dict] = []
        for hit in resp.get("hits", {}).get("hits", []):
            score = float(hit.get("_score", 0.0))
            if score < threshold:
                continue

            src = hit.get("_source", {})
            results.append(
                {
                    "article_id": src.get("article_id"),
                    "title": src.get("title", ""),
                    "content": src.get("chunk_content", ""),
                    "chunk_index": src.get("chunk_index", 0),
                    "score": score,
                    "chunk_id": src.get("chunk_id"),
                    "source_hash": src.get("source_hash"),
                    "chunker_version": src.get("chunker_version"),
                    "section_path": src.get("section_path", []),
                    "chunk_type": src.get("chunk_type"),
                    "user_id": src.get("user_id"),
                    "category_id": src.get("category_id"),
                    "publish_time": src.get("publish_time"),
                    "tags": src.get("tags", []),
                }
            )

        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return results[:top_k]


class EsChunkSearch(BaseEsClient):
    """RAG lexical retrieval uses the exact chunk corpus as KNN; article search stays separate."""
    INDEX = EsVectorStore.INDEX

    async def search(self, keyword: str, page_size: int = 20, filters: dict | None = None) -> list[dict]:
        query = {"multi_match": {"query": keyword, "fields": ["chunk_content.zh^3", "section_path.zh", "title.zh^0.5", "chunk_content^0.3", "section_path^0.1", "title^0.05"]}}
        if filters:
            query = {"bool": {"must": [query], "filter": [filters]}}
        response = await self.client.search(index=self.INDEX, body={"query": query, "size": page_size,
                                                                   "sort": [{"_score": {"order": "desc"}}]})
        return [{**hit.get("_source", {}), "content": hit.get("_source", {}).get("chunk_content", ""),
                 "score": float(hit.get("_score") or 0)} for hit in response.get("hits", {}).get("hits", [])]


class EsComponent(BaseEsClient):
    """全文检索客户端（article）"""

    INDEX = "article"

    async def search(self, keyword: str, page_size: int = 5, filters: dict | None = None) -> list[dict]:
        """
        全文检索（title + tags）
        对应 Java: EsComponent.search()
        """
        body = {
            "query": {
                "multi_match": {
                    "query": keyword,
                    "fields": ["title.zh^4", "tags", "summary.zh^2", "content.zh^0.5", "title^0.4"],
                }
            },
            "size": page_size,
            "sort": [{"_score": {"order": "desc"}}],
        }

        if filters:
            body["query"] = {"bool": {"must": [body["query"]], "filter": [filters]}}
        resp = await self.client.search(index=self.INDEX, body=body)

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
