"""
联网搜索工具（博查）
对应 Java: BochaSearchTool.java
"""
import httpx
from langchain_core.tools import tool

from app.config import settings
from app.services.dependency_policy import web_policy, DependencyHTTPError, DependencyUnavailable

_client = httpx.AsyncClient(timeout=12.0)


class WebSearchError(ConnectionError):
    """Safe external-tool error; credentials and response bodies are never exposed."""


def _search_error(code) -> WebSearchError:
    code = code if isinstance(code, int) else None
    reason = {401: "博查 API Key 无效或已过期", 403: "博查搜索余额不足",
              429: "博查搜索请求过于频繁"}.get(code, "博查搜索服务暂时不可用")
    return WebSearchError(reason)


async def do_search(query: str, size: int = 5) -> list[dict]:
    """Transport failures are errors; an empty successful response is no evidence."""
    if not settings.BOCHA_API_KEY:
        raise WebSearchError("联网检索未配置 API Key")

    headers = {
        "Authorization": f"Bearer {settings.BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "count": max(1, min(50, size)),
        "freshness": "noLimit",
        "summary": True,
    }

    try:
        async def request():
            response = await _client.post(settings.BOCHA_BASE_URL, headers=headers, json=payload)
            if not response.is_success: raise DependencyHTTPError(response.status_code)
            try:
                application = response.json()
            except ValueError:
                return response
            if isinstance(application, dict) and isinstance(application.get('code'), int) and application['code'] != 200:
                raise DependencyHTTPError(application['code'])
            return response
        resp = await web_policy.run(request)
    except DependencyHTTPError as exc:
        raise _search_error(exc.status_code) from None
    except DependencyUnavailable:
        raise WebSearchError("联网搜索暂时熔断，请稍后重试") from None
    except (httpx.RequestError, TimeoutError):
        raise WebSearchError("博查搜索连接失败或超时") from None
    if not resp.is_success:
        raise _search_error(resp.status_code)
    try:
        data = resp.json()
        if not isinstance(data, dict) or data.get("code") != 200:
            raise _search_error(data.get("code") if isinstance(data, dict) else None)
        body = data.get("data") or {}
        results = (body.get("webPages") or {}).get("value") or []
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise ValueError("invalid results")
    except (ValueError, AttributeError):
        raise WebSearchError("博查搜索返回格式异常") from None
    return [{"title": item.get("name", ""), "content": item.get("summary") or item.get("snippet") or "",
             "url": item.get("url", ""), "source": "web"} for item in results]


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
