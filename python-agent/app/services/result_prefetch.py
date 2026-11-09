"""Conservative first-decision prefetch of explicitly named, authorized results."""
import asyncio
import json
import re
from time import perf_counter

from fastapi import HTTPException

from app.config import settings
from app.utils.context_budget import ensure_request_budget, input_budget, request_tokens
from app.utils.token_utils import count_tokens


def candidates(state, view):
    message = state.get('user_message') or ''
    if re.search(r'(?:不要|禁止|别|无需|不用|不许|不准|不得)(?:再)?(?:读取|回读|读|使用|引用)', message):
        return []
    sources = state.get('task_results') or {}
    explicit = [tid for tid, source in sources.items() if re.search(r'(?<![a-zA-Z0-9_:])' + re.escape(tid) + r'(?![a-zA-Z0-9_:])', message)
        or any('[' + str(c['id']) + ']' in message for c in source.get('citations') or [])]
    if not 1 <= len(explicit) <= 2:
        return []
    quoted = re.findall(r'[“「"]([^”」"\n]{2,200})[”」"]', message)
    phrases = re.findall(r'(?:提取|查找|定位|核对)(?:其中的?|里面的?|里的?|中的?)?([^，。；：:,\n]{2,80})', message)
    words = list(dict.fromkeys(word.strip() for word in [*quoted, *phrases]))[:5]
    found = []
    for tid in explicit:
        source = sources[tid]
        # Only platform-public snapshots; no read aliases, private inputs or web.
        if (view.get(tid, {}).get('content_scope') != 'index_only'
                or source.get('kind') != 'search' or source.get('retrieval_target') != 'knowledge'
                or source.get('private_context') or source.get('source_context')
                or source.get('tool_name') in ('web_search', 'read_webpage')
                or any(c.get('url') and not c.get('articleId') for c in source.get('citations') or [])):
            continue
        ids = [str(c['id']) for c in source.get('citations') or [] if '[' + str(c['id']) + ']' in message]
        if any(sum(any(str(c['id']) == cid for c in other.get('citations') or []) for other in sources.values()) > 1 for cid in ids):
            continue
        matched = [word for word in words if word.casefold() in (source.get('result') or '').casefold()]
        request = None
        if len(ids) == 1:
            request = {'source_task_id': tid, 'citation_id': ids[0], 'max_chars': 3000}
        elif matched:
            request = {'source_task_id': tid, 'queries': matched, 'max_chars': 3000}
        if request and not already_loaded(tid, source, request, view):
            found.append(request)
    return found


def already_loaded(tid, source, request, view):
    visible_reads = [read for item in view.values() if item.get('result')
        and item.get('content_scope') not in ('index_only', 'shared_result')
        for read in item.get('result_reads') or [] if read['source_task_id'] == tid
        and read['source_version'] == view.get(tid, {}).get('source_version')]
    if cid := request.get('citation_id'):
        text = (source.get('citation_contents') or {}).get(cid)
        return text is not None and any(read['field'] == 'citation:' + cid and read['start_char'] == 0
            and read['end_char'] >= min(3000, len(text)) for read in visible_reads)
    text = source.get('result') or ''
    hits = [re.search(re.escape(word), text, re.IGNORECASE) for word in request.get('queries') or []]
    return bool(hits) and all(hit is not None and any(read['field'] == 'result'
        and read['start_char'] <= hit.start() and read['end_char'] >= hit.end() for read in visible_reads) for hit in hits)


def has_prefetch_hint(state):
    # Skip the speculative render for new work and unrelated messages. This
    # hint can only avoid work; the real view/authorization still decides access.
    current = set(state.get('action_task_ids') or [])
    index = {tid: {'content_scope': 'index_only'} for tid in state.get('task_results') or {} if tid not in current}
    return bool(candidates(state, index))


async def prepare_prefetch(state, messages, schemas, *, fence):
    started = perf_counter()
    stats = {'status': 'skipped', 'reason': 'disabled', 'source_count': 0, 'added_tokens': 0}
    if not settings.CONTEXT_RESULT_PREFETCH_ENABLED or state.get('main_round', 0) != 0:
        return {}, stats
    payload = json.loads(messages[1].content)
    view = payload.get('successful_tasks') or {}
    requests = candidates(state, view)
    if not requests:
        return {}, {**stats, 'reason': 'no_explicit_unloaded_source'}
    before = request_tokens(messages, schemas)
    # Prefetch must not cause compaction or refill a just-compacted window.
    ceiling = min(input_budget(), settings.CONTEXT_COMPACT_TRIGGER_TOKENS - 1024)
    if (state.get('context_compaction') or {}).get('status') == 'compacted':
        ceiling = min(ceiling, settings.CONTEXT_COMPACT_TARGET_TOKENS - 1024)
    if ceiling - before < 4096:
        return {}, {**stats, 'reason': 'budget'}
    await fence(state)
    try:
        from app.models.main_tool import ReadTaskResults, task_fields
        from app.graph.staged_plan import ExecutionTask
        from app.graph.staged_runtime import task_context
        from app.services.context_tools import read_task_results
        call = ReadTaskResults(name='read_task_results', args={'requests': requests})
        task = ExecutionTask(task_id='prefetch', actor='main', **task_fields(call))
        context = task_context(state, task)
        context['readable_task_results'] = state.get('task_results') or {}
        result = await asyncio.wait_for(read_task_results(context), 3)
        await fence(state)
        results = json.loads(result['result'])['results']
        prefetched = {}
        for item in results:
            tid = item['source_task_id']
            reads = [read for read in result['result_reads'] if read['source_task_id'] == tid]
            if not reads:
                continue
            cids = {cid for read in reads for cid in read['citation_ids']}
            prefetched[tid] = {**view[tid], 'result': json.dumps(item, ensure_ascii=False),
                'content_scope': 'excerpt', 'result_reads': reads,
                'citations': [c for c in result['citations'] if str(c['id']) in cids]}
        if not prefetched:
            return {}, {**stats, 'reason': 'no_match'}
        delta = count_tokens(json.dumps(prefetched, ensure_ascii=False))
        if delta > 4096:
            return {}, {**stats, 'reason': 'fragment_budget'}
        candidate_payload = {**payload, 'successful_tasks': {**view, **prefetched}}
        from langchain_core.messages import HumanMessage
        candidate = [messages[0], HumanMessage(content=json.dumps(candidate_payload, ensure_ascii=False)), *messages[2:]]
        if ensure_request_budget(candidate, schemas) > ceiling:
            return {}, {**stats, 'reason': 'request_budget'}
        return prefetched, {'status': 'hit', 'reason': 'explicit_source', 'source_count': len(prefetched),
            'added_tokens': delta, 'prepare_ms': round((perf_counter()-started)*1000, 2)}
    except HTTPException:
        raise
    except Exception:
        await fence(state)
        return {}, {**stats, 'reason': 'validation_or_lookup_failed'}
