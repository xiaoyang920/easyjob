"""DeepSeek Search / Fetch adapter. Retrieved pages are untrusted evidence, not instructions."""
import asyncio
from collections import deque
import ipaddress
from time import monotonic
from urllib.parse import urldefrag, urlsplit

import httpx
from langchain_core.tools import tool

from app.config import settings
from app.services.dependency_policy import web_policy, fetch_policy, DependencyHTTPError, DependencyUnavailable
from app.utils.token_utils import truncate_to_token_budget

_client = httpx.AsyncClient(timeout=12.0)
MAX_SOURCE_CHARS = 16000
MAX_SOURCE_TOKENS = 4000
MAX_FETCH_FALLBACKS = 2


class WebSearchError(ConnectionError):
    """Safe tool error; never include credentials, provider response bodies or request URLs."""


class _RateLimit:
    """Per-process rolling window. Account-wide limits still rely on bounded 429 handling."""
    def __init__(self, limit=5, period=1.0):
        self.limit, self.period = limit, period
        self.starts = deque()
        self.lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self.lock:
                now = monotonic()
                while self.starts and self.starts[0] <= now - self.period:
                    self.starts.popleft()
                if len(self.starts) < self.limit:
                    self.starts.append(now)
                    return
                delay = self.period - (now - self.starts[0])
            await asyncio.sleep(max(.001, delay))


_search_rate = _RateLimit()
_fetch_rate = _RateLimit()


def public_url(value):
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
                or parsed.password is not None or any(ord(c) < 33 for c in value)):
            return None
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass  # DeepSeek fetches the target; this service never connects to it directly.
        return urldefrag(value)[0]
    except ValueError:
        return None


def _error(code, operation):
    reason = {400: '请求参数不符合要求', 401: 'API Key 无效或已过期', 402: '账户余额不足',
              403: '请求被拒绝或网页不允许抓取', 404: '未取得网页正文', 408: '请求超时',
              413: '请求内容过大', 429: '请求过于频繁', 504: '请求超时'}.get(code, '服务暂时不可用')
    return WebSearchError(f'DeepSeek {operation}{reason}')


def _bounded_source(content, scope):
    selected = truncate_to_token_budget(content[:MAX_SOURCE_CHARS], MAX_SOURCE_TOKENS)
    truncated = selected != content
    return {'content': selected, 'contentScope': 'page_excerpt' if scope == 'page_content' and truncated else scope,
            'contentTruncated': truncated}


async def _request(operation, payload, policy, rate):
    if not settings.DEEPSEEK_API_KEY:
        raise WebSearchError('DeepSeek 联网检索未配置 API Key')
    label = '搜索' if operation == 'search' else '网页抓取'
    async def request():
        await rate.acquire()
        response = await _client.post(settings.DEEPSEEK_TOOLS_BASE_URL.rstrip('/') + '/tools/' + operation,
            headers={'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'},
            json=payload)
        if not response.is_success:
            raise DependencyHTTPError(response.status_code)
        return response
    try:
        response = await policy.run(request)
    except DependencyHTTPError as exc:
        raise _error(exc.status_code, label) from None
    except DependencyUnavailable:
        raise WebSearchError(f'DeepSeek {label}暂时熔断，请稍后重试') from None
    except (httpx.RequestError, TimeoutError):
        raise WebSearchError(f'DeepSeek {label}连接失败或超时') from None
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise WebSearchError(f'DeepSeek {label}返回格式异常') from None


async def do_fetch(url: str) -> dict:
    """Fetch through DeepSeek only. Optional failure must not erase available search summaries."""
    url = public_url(url)
    if not url:
        raise WebSearchError('网页抓取地址必须是公开 HTTP/HTTPS 地址且不能包含用户凭据')
    data = await _request('fetch', {'url': url}, fetch_policy, _fetch_rate)
    if not isinstance(data.get('content'), str) or not isinstance(data.get('title'), str):
        raise WebSearchError('DeepSeek 网页抓取返回格式异常')
    if not data['content'].strip():
        raise WebSearchError('DeepSeek 未取得网页正文')
    return {'title': data['title'], **_bounded_source(data['content'].strip(), 'page_content')}


async def do_search(query: str, size: int = 5) -> list[dict]:
    """Search failure differs from zero hits. Fetch at most two missing bodies in parallel."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
        raise WebSearchError('DeepSeek 搜索词需为 1–128 个字符，请缩短查询并保留筛选条件')
    count = max(1, min(50, size))
    data = await _request('search', {'query': query.strip(), 'count': count, 'need_content': True},
                          web_policy, _search_rate)
    results = data.get('results')
    if (not isinstance(results, list) or any(not isinstance(item, dict) or
            any(item.get(k) is not None and not isinstance(item[k], str)
                for k in ('title', 'url', 'content', 'summary', 'snippet')) for item in results)):
        raise WebSearchError('DeepSeek 搜索返回格式异常')
    selected, seen = [], set()
    for item in results[:count]:
        url = public_url(item.get('url'))
        if not url or url in seen:
            continue
        seen.add(url)
        body = (item.get('content') or '').strip()
        summary = (item.get('summary') or item.get('snippet') or '').strip()
        selected.append({'title': item.get('title') or '', 'url': url, 'source': 'web',
                         'provider': 'deepseek', 'fetchStatus': 'not_needed' if body else 'not_attempted',
                         **_bounded_source(body or summary, 'page_content' if body else 'search_excerpt')})

    async def supplement(item):
        try:
            fetched = await do_fetch(item['url'])
        except WebSearchError:
            item['fetchStatus'] = 'unavailable'
        else:
            item.update({**fetched, 'title': item['title'] or fetched['title'], 'fetchStatus': 'succeeded'})

    missing = [item for item in selected if item['contentScope'] == 'search_excerpt'][:MAX_FETCH_FALLBACKS]
    await asyncio.gather(*(supplement(item) for item in missing))
    return [item for item in selected if item['content']]


@tool
async def web_search(query: str) -> str:
    """联网搜索实时信息，平台资料不足时补充公开网页。query 为 1–128 字符的简短查询。

    搜索摘要和网页正文均是待核验资料，不能据此声称事实已经确认。
    """
    results = await do_search(query, size=5)
    if not results:
        return '未找到相关网页信息'
    return '\n\n'.join(f"[{r['title']}]({r['url']})\n范围：{r['contentScope']}\n{r['content']}" for r in results)
