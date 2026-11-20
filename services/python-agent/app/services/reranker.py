"""
Reranker 服务
对应 Java: RerankerService.java

调用阿里云 DashScope Rerank API：
https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
"""
import logging
import math
import httpx

log = logging.getLogger(__name__)

from app.config import settings
from app.services.dependency_policy import rerank_policy, DependencyHTTPError


class RerankerService:
    API_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    MODEL = "qwen3-vl-rerank"
    MAX_CHUNKS_PER_ARTICLE = 3

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    async def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """
        对候选文档进行精排

        :param query: 用户查询
        :param candidates: 候选文档列表，每项包含 content/title
        :return: 按相关性降序后的文档列表（最多 topK）
        """
        if not candidates:
            return []

        documents = [self._to_rerank_text(doc) for doc in candidates]

        payload = {
            "model": self.MODEL,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                "top_n": min(settings.RERANK_TOP_K * self.MAX_CHUNKS_PER_ARTICLE, len(documents)),
            },
        }

        headers = {
            "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            async def request():
                response = await self.client.post(self.API_URL, headers=headers, json=payload)
                response.raise_for_status()
                return response
            resp = await rerank_policy.run(request)
            body = resp.json()

            if not isinstance(body.get('output'), dict) or 'results' not in body['output']:
                raise ValueError('Missing rerank results')
            result_items = body['output']['results']
            if not isinstance(result_items, list):
                raise ValueError('Malformed rerank results')
            ranked = []
            seen_indices = set()
            for item in result_items:
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if (isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(candidates)
                        or idx in seen_indices or isinstance(score, bool) or not isinstance(score, (int, float))
                        or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError('Malformed rerank index or relevance score')
                seen_indices.add(idx)

                doc = dict(candidates[idx])
                doc["score"] = score
                ranked.append(doc)

            ranked = [d for d in ranked if d.get("score", 0.0) >= settings.RELEVANCE_THRESHOLD]
            if ranked:
                return self._select_diverse(sorted(ranked, key=lambda d: d["score"], reverse=True))

            # A successful relevance rejection is not an infrastructure outage.
            return []

        except Exception as e:
            log.warning("Reranker API 调用失败，使用粗排结果: %s", e)
            fallback = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
            return [{**doc, "rerank_status": "degraded", "rerank_reason": "reranker_unavailable"}
                    for doc in self._select_diverse(fallback)]

    @classmethod
    def _select_diverse(cls, ranked: list[dict]) -> list[dict]:
        selected, counts, seen = [], {}, set()
        for doc in ranked:
            article_id = str(doc.get("article_id") or "")
            key = doc.get("chunk_id") or (article_id, doc.get("chunk_index", 0))
            if key in seen or counts.get(article_id, 0) >= cls.MAX_CHUNKS_PER_ARTICLE:
                continue
            seen.add(key)
            counts[article_id] = counts.get(article_id, 0) + 1
            selected.append(doc)
            if len(selected) >= settings.RERANK_TOP_K:
                break
        return selected

    @staticmethod
    def _to_rerank_text(doc: dict) -> str:
        title = " > ".join(doc.get("section_path") or []) or doc.get("title", "")
        content = doc.get("content", "")
        if title:
            return f"标题：{title}\n内容：{content}"
        return content
