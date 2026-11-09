"""Model-facing views; immutable results remain in the fenced Redis checkpoint."""
from app.config import settings
from app.utils.context_budget import json_text
from app.utils.token_utils import count_tokens
from app.services.result_access import RESULT_READ_TOOLS, result_version, compact_read_view

CONTEXT_READ_TOOLS = RESULT_READ_TOOLS | {'search_conversation_history', 'read_conversation_messages'}


def context_read_count(state):
    return sum(r.get('tool_name') in CONTEXT_READ_TOOLS and not r.get('previous_run_id')
               for r in (state.get('task_results') or {}).values())


def result_directory(tid, result, cost):
    from app.services.result_locator import sections
    outline, outline_more = sections(result.get('result') or '')
    view = {k: result.get(k) for k in
            ('kind', 'actor', 'tool_name', 'retrieval_target', 'retrieval_report')}
    view.update(task_id=tid, status=result.get('status', 'succeeded'),
        instruction=(result.get('instruction') or '')[:1000], result='', content_scope='index_only',
        result_tokens=cost, total_chars=len(result.get('result') or ''),
        source_version=result.get('source_version') or result_version(result),
        read_tool='read_task_result', read_methods=['range', 'query', 'queries', 'citation_id', 'section_id', 'cursor'],
        citations=[{k: c[k] for k in ('id', 'title', 'articleId', 'sourceHash') if k in c}
                   for c in result.get('citations') or []],
        notice='正文未载入；目录不是证据。请定位读取，不能据目录声称读过全文。')
    if outline:
        view.update(sections=outline, more_sections=outline_more)
    return view


def project_results(results, *, selective=False, priority=()):
    limit = settings.CONTEXT_TOOL_INLINE_TOKENS
    if not selective and count_tokens(json_text(results)) <= limit:
        return results
    projected, remaining, seen, coverage = {}, limit, {}, {}
    # New results first. Private documents remain explicit mandatory inputs:
    # the public result reader cannot be used to recover private snapshots.
    newest = next(reversed(results), None)
    for tid, result in reversed(list(results.items())):
        if selective:
            result = compact_read_view(result, coverage)
            if result.get('content_scope') == 'shared_result':
                projected[tid] = result
                continue
        cost = count_tokens(json_text(result))
        private = result.get('private_context') or result.get('retrieval_target') in ('drafts', 'editor', 'memory')
        # Deduplicate only byte-identical public bodies with identical source metadata.
        # Similar text, different hashes, or different citation IDs remain separate.
        signature = json_text([result.get('result'), result.get('citations'), result.get('evidence_scope')])
        if not private and signature in seen:
            projected[tid] = {**result, 'result': '', 'content_scope': 'shared_result', 'same_as': seen[signature]}
            continue
        eligible = not selective or cost <= settings.CONTEXT_RESULT_SMALL_TOKENS or tid in priority
        if (eligible and cost <= remaining) or private or (tid == newest and result.get('tool_name') in RESULT_READ_TOOLS):
            projected[tid] = result
            remaining -= cost
            if not private: seen[signature] = tid
            if selective:
                for read in result.get('result_reads') or []:
                    key = (read['source_task_id'], read['source_version'], read['field'])
                    coverage.setdefault(key, []).append((read['start_char'], read['end_char'], tid))
        else:
            projected[tid] = result_directory(tid, result, cost)
    return {tid: projected[tid] for tid in results}


def context_breakdown(messages, schemas=()):
    from app.utils.context_budget import message_tokens, request_tokens
    import json
    total = request_tokens(messages, schemas)
    parts = {'system': message_tokens(messages[0]) if messages else 0}
    if len(messages) > 1:
        try:
            payload = json.loads(messages[1].content)
        except (ValueError, TypeError):
            payload = {}
        groups = {'history': ('history', 'history_summary', 'history_window'),
                  'tool_results': ('successful_tasks', 'previous_run'),
                  'memory': ('memory', 'user_profile', 'active_constraints'),
                  'task_state': ('task_context',)}
        for name, keys in groups.items():
            parts[name] = count_tokens(json_text({k: payload[k] for k in keys if k in payload}))
        parts['omitted_tool_results'] = sum(r.get('content_scope') == 'index_only'
            for r in payload.get('successful_tasks', {}).values())
        parts['omitted_messages'] = payload.get('history_window', {}).get('omitted_messages', 0)
        parts['unloaded_history'] = int(payload.get('history_window', {}).get('earlier_history_available', False))
    parts['current_and_images'] = sum(message_tokens(m) for m in messages[2:])
    parts['total_tokens'] = total
    # JSON framing, other execution metadata and schemas are accounted for here.
    parts['other_and_schemas'] = max(0, total - sum(parts.get(k, 0) for k in
        ('system', 'history', 'tool_results', 'memory', 'task_state', 'current_and_images')))
    return parts
