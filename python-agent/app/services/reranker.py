"""
Reranker 服务
对应 Java: RerankerService.java

调用阿里云 DashScope Rerank API：
https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
"""
import logging
import httpx

log = logging.getLogger(__name__)

from app.config import settings


class RerankerService:
    API_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    MODEL = "qwen3-vl-rerank"

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
                "top_n": min(settings.RERANK_TOP_K, len(documents)),
            },
        }

        headers = {
            "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            resp = await self.client.post(self.API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()

            result_items = body.get("output", {}).get("results", [])
            ranked = []
            for item in result_items:
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if idx is None or idx < 0 or idx >= len(candidates):
                    continue

                doc = dict(candidates[idx])
                doc["score"] = score
                ranked.append(doc)

            ranked = [d for d in ranked if d.get("score", 0.0) >= settings.RELEVANCE_THRESHOLD]
            if ranked:
                return ranked

            # 阈值过滤后为空，回退 topK
            fallback = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
            return fallback[: settings.RERANK_TOP_K]

        except Exception as e:
            log.warning("Reranker API 调用失败，使用粗排结果: %s", e)
            fallback = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
            return fallback[: settings.RERANK_TOP_K]

    @staticmethod
    def _to_rerank_text(doc: dict) -> str:
        title = doc.get("title", "")
        content = doc.get("content", "")
        if title:
            return f"标题：{title}\n内容：{content}"
        return content
