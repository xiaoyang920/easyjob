"""Read exact public pages into the normal evidence/citation pipeline."""
import asyncio
import re

from app.config import settings
from app.tools.web_search import do_fetch, public_url, WebSearchError


def referenced_urls(text):
    urls = set()
    for raw in re.findall(r'https?://[^\s<>"\u3000，。；！？）]+', text or ''):
        url = raw.rstrip('.,;:!?]}＞>')
        while url.endswith(')') and url.count(')') > url.count('('):
            url = url[:-1]
        if valid := public_url(url):
            urls.add(valid)
    return urls


async def read_pages(state):
    from app.security.capabilities import require_capability
    from app.services.agent_events import activity
    require_capability(state, 'web_search')
    requested = state['current_task']['urls']
    allowed = referenced_urls(state.get('request_goal', state.get('user_message', '')))
    allowed.update(c['url'] for c in state.get('citations', []) if c.get('url'))
    allowed.update(state.get('known_page_urls', []))
    for message in state.get('history_messages', []):
        if isinstance(message, dict) and message.get('role') == 'user':
            allowed.update(referenced_urls(message.get('content', '')))
    if any(not public_url(url) or public_url(url) not in allowed for url in requested):
        raise PermissionError('网页地址必须来自用户提供的链接或已经取得的来源')
    await activity(state, 'read_pages', '读取指定网页')
    citations, contents, failures = [], {}, 0
    remaining = max(0, settings.TASK_RESULT_MAX_CHARS - 4000)
    for raw in dict.fromkeys(requested):
        url = public_url(raw)
        try:
            page = await asyncio.wait_for(do_fetch(url), settings.RETRIEVAL_TIMEOUT_SECONDS)
        except (WebSearchError, TimeoutError):
            failures += 1
            continue
        if remaining <= 0:
            failures += 1
            continue
        content = page['content'][:remaining]
        truncated = page['contentTruncated'] or len(content) < len(page['content'])
        remaining -= len(content) + len(page['title']) + 100
        cid = f"{state.get('task_id', 'page')}:web{len(citations) + 1}"
        citations.append({'id': cid, 'articleId': '', 'title': page['title'], 'chunkIndex': 0,
                          'excerpt': content[:1200], 'url': url, 'source': 'web',
                          'contentScope': 'page_excerpt' if truncated else page['contentScope'], 'contentTruncated': truncated})
        contents[cid] = content
    await activity(state, 'read_pages', '读取指定网页', 'done' if citations else 'error', f'已读取 {len(citations)} 个网页，{failures} 个未能读取')
    return {'status': 'succeeded' if citations else 'tool_error', 'citations': citations,
            'article_cards': [], 'citation_contents': contents,
            'rag_context': '\n\n'.join(f"[{c['id']}] {c['title']}\n{contents[c['id']]}" for c in citations),
            'result': '指定网页未能读取，未用其他网页替代。' if not citations else '',
            'retrieval_report': {'assessment_owner': 'main', 'platform': {'status': 'not_requested', 'candidates': 0},
                'web': {'status': 'found' if citations else 'error', 'provider': 'deepseek', 'candidates': len(citations), 'failed_pages': failures}}}
