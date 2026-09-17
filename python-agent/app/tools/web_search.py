"""
联网搜索工具（博查）
对应 Java: BochaSearchTool.java
"""
import httpx
from langchain_core.tools import tool

from app.config import settings

_API_URL = "https://api.bochaai.com/v1/web-search"
_client = httpx.AsyncClient(timeout=12.0)


async def do_search(query: str, size: int = 5) -> list[dict]:
    """底层 HTTP 调用，失败时返回空列表"""
    if not settings.BOCHA_API_KEY:
        return []

    headers = {
        "Authorization": f"Bearer {settings.BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "size": size,
        "freshness": "noLimit",
        "summary": True,
    }

    try:
        resp = await _client.post(_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", {}).get("webPages", {}).get("value", [])
        return [
            {
                "title": item.get("name", ""),
                "content": item.get("summary", item.get("snippet", "")),
                "url": item.get("url", ""),
                "source": "web",
            }
            for item in results
        ]
    except Exception:
        return []


@tool
async def web_search(query: str) -> str:
    """
    联网搜索实时信息。
    适合：最新资讯、时效性强的问题、平台文章里找不到的内容。
    不适合：可以从已有参考资料直接回答的问题。

    Args:
        query: 搜索关键词，尽量简洁精确，不超过 20 字
    """
    results = await do_search(query, size=5)
    if not results:
        return "未找到相关网页信息"
    return "\n".join([f"- [{r['title']}] {r['content']}" for r in results[:3]])
