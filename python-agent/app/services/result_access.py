"""Pure result addressing and exact slices of the current execution snapshot.

No database, Redis, model or network clients. Permission/freshness guards belong
to the calling reader; persisted read metadata is produced only by the backend.
"""
import hashlib
import json
import re
from itertools import islice

from app.utils.context_budget import json_text
from app.utils.token_utils import count_tokens

RESULT_READ_TOOLS = frozenset({'read_task_result', 'read_task_results'})


def result_version(source):
    from app.utils.context_calculations import active_calculations
    calculation = active_calculations.get()
    if calculation is not None:
        calculation.stats['result_hashes'] += 1
    fields = [source.get('result'), source.get('citations'), source.get('citation_contents')]
    if source.get('evidence_scope'):
        fields.append(source['evidence_scope'])
    canonical = json.dumps(fields,
                           ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def resolve_source(sources, task_id, validate):
    """Resolve new/legacy read aliases, checking every hop and its root."""
    seen = set()
    while True:
        if task_id in seen or len(seen) >= 16:
            raise ValueError('结果回读来源存在循环')
        seen.add(task_id)
        source = sources.get(task_id)
        validate(task_id, source)
        if source.get('tool_name') not in RESULT_READ_TOOLS:
            return task_id, source
        reads = source.get('result_reads') or []
        ids = {r['source_task_id'] for r in reads}
        if not reads:
            # Old checkpoints used a JSON envelope without backend lineage.
            try:
                original = json.loads(source.get('result') or '').get('source_task_id')
            except (ValueError, AttributeError):
                original = None
            if original and original in sources:
                task_id = original
                continue
            return task_id, source  # Legacy captured snapshot, no hidden fetch.
        if len(ids) != 1:
            raise ValueError('批量读取结果包含多个来源，请选择原始 source_task_id')
        original = next(iter(ids))
        if original not in sources:
            raise ValueError('原始结果未载入当前运行，请重新取得原资料')
        if any(r['source_version'] != result_version(sources[original]) for r in reads):
            raise ValueError('回读的原始结果版本已变化')
        task_id = original


def prefix_end(text, start, end, token_budget):
    if count_tokens(text[start:end]) <= token_budget:
        return end
    low, high = start, end
    while low < high:
        mid = (low + high + 1) // 2
        if count_tokens(text[start:mid]) <= token_budget:
            low = mid
        else:
            high = mid - 1
    return low


def compact_read_view(result, coverage):
    """Subtract already visible read spans, never change the stored outcome."""
    if not result.get('result_reads'):
        return result
    try:
        envelope = json.loads(result['result'])
        payloads = envelope.get('results', [envelope])
        updated, spans, shared = [], [], set()
        for payload in payloads:
            pieces = []
            key = (payload['source_task_id'], payload['source_version'], payload['field'])
            for fragment in payload.get('fragments', [payload] if 'content' in payload else []):
                start, end = fragment['start_char'], fragment['next_start_char']
                pending = [(start, end)]
                for a, b, owner in coverage.get(key, []):
                    if a < end and b > start:
                        shared.add(owner)
                    pending = [(lo, hi) for lo, hi in
                        (part for lo, hi in pending for part in ((lo, min(hi, a)), (max(lo, b), hi))) if lo < hi]
                for lo, hi in pending:
                    piece = {**fragment, 'content': fragment['content'][lo-start:hi-start],
                        'start_char': lo, 'next_start_char': hi,
                        'has_more': hi < payload['total_chars'], 'content_scope': 'excerpt'}
                    pieces.append(piece)
                    origin = next(r for r in result['result_reads'] if
                        (r['source_task_id'], r['source_version'], r['field']) == key
                        and r['start_char'] <= lo and r['end_char'] >= hi)
                    spans.append({**origin, 'start_char': lo, 'end_char': hi})
            if pieces:
                head = {k: v for k, v in payload.items() if k not in
                        ('content', 'fragments', 'start_char', 'next_start_char', 'has_more', 'content_scope')}
                updated.append({**head, **pieces[0]} if len(pieces) == 1 else
                               {**head, 'fragments': pieces, 'content_scope': 'excerpt'})
        if not updated and shared:
            return {**result, 'result': '', 'content_scope': 'shared_result', 'same_as_tasks': sorted(shared)}
        if shared:
            payload = {'results': updated} if 'results' in envelope else updated[0]
            return {**result, 'result': json.dumps(payload, ensure_ascii=False), 'result_reads': spans,
                    'shared_with_tasks': sorted(shared)}
    except (ValueError, KeyError, TypeError, StopIteration):
        pass  # Old envelopes remain readable; they do not claim span coverage.
    return result


def read_selection(task_id, source, args, *, max_chars, max_tokens, selection=None):
    from app.services.result_locator import locate, cursor_encode
    plan = selection or locate(task_id, source, args)
    text, field, citations, version = plan.text, plan.field, plan.citations, plan.version
    limit = min(args.get('max_chars', 12000), max_chars)
    ranges = []
    matches = plan.matches
    if matches is not None:
        chosen = matches[:min(3, max(1, max_tokens // 32), max(1, limit // 500))]
        piece_limit = max(1, limit // max(1, len(chosen)))
        for lo, hi in chosen:
            start = max(plan.start, lo - min(400, piece_limit // 4))
            end = min(plan.end, max(start + piece_limit, hi))
            if ranges and start <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
            else:
                ranges.append((start, end))
    else:
        ranges = [(plan.start, min(plan.end, plan.start + limit))]
    fragments, reads = [], []
    remaining, remaining_chars = max_tokens, limit
    for index, (start, end) in enumerate(ranges):
        range_end = end
        end = min(end, start + remaining_chars)
        end = prefix_end(text, start, end, max(1, remaining // (len(ranges) - index)))
        if matches:
            hit = next((hit for hit in matches if start <= hit[0] < range_end), None)
            if hit and end < hit[1]:
                start = hit[0]
                end = prefix_end(text, start, min(plan.end, start + remaining_chars), max(1, remaining // (len(ranges)-index)))
                if end < hit[1]:
                    raise ValueError('片段预算不足以容纳完整关键词，请增加读取预算')
        if end <= start and text:
            continue
        content = text[start:end]
        remaining -= count_tokens(content)
        remaining_chars -= len(content)
        fragment = {'content': content, 'start_char': start, 'next_start_char': end,
                    'has_more': end < len(text),
                    'content_scope': 'full' if start == 0 and end == len(text) else 'excerpt'}
        fragments.append(fragment)
        if end > start:
            reads.append({'source_task_id': task_id, 'source_version': version, 'field': field,
                          'start_char': start, 'end_char': end,
                          'citation_ids': [str(c['id']) for c in citations]})
    payload = {'source_task_id': task_id, 'source_version': version, 'field': field,
               'total_chars': len(text),
               'notice': '当前任务结果的原文快照；仅本次返回的范围已载入，不能据此声称读完全文。'}
    if len(fragments) == 1:
        payload.update(fragments[0])
    else:
        payload.update(fragments=fragments, content_scope='excerpt')
    covered = [hit for hit in (matches or []) if any(f['start_char'] <= hit[0] and f['next_start_char'] >= hit[1] for f in fragments)]
    if matches is not None:
        more_matches = bool(matches) and (len(matches) > len(covered) or len(matches) == 4)
        position = covered[-1][1] if covered else plan.start
        payload.update(matched=bool(matches), more_matches=more_matches, has_more_matches=more_matches)
    else:
        position = fragments[-1]['next_start_char'] if fragments else plan.start
        more_matches = False
    content_more = bool(fragments) and fragments[-1]['next_start_char'] < plan.end
    continuation = more_matches if matches is not None else content_more
    payload.update(has_more_content=content_more,
        budget_truncated=any(f['next_start_char'] < end for f, (_, end) in zip(fragments, ranges)),
        next_cursor=cursor_encode(plan.binding, position) if continuation and position > plan.start else None)
    if field == 'result' and len(citations) > 1:
        # Raw RAG bodies carry stable [citation_id] sections. Only sections
        # intersecting returned text may become readback citations.
        markers = sorted((text.find('[' + str(c['id']) + ']'), c) for c in citations
                         if '[' + str(c['id']) + ']' in text)
        if markers:
            selected = set()
            for index, (start, c) in enumerate(markers):
                end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
                if any(r['start_char'] < end and r['end_char'] > start for r in reads):
                    selected.add(str(c['id']))
            citations = [c for c in citations if str(c['id']) in selected]
            for read in reads:
                read['citation_ids'] = [str(c['id']) for c in citations]
    return payload, reads, citations


def loaded_result_dependencies(view, dependencies):
    """Resolve a directory ID to visible, version-matched read tasks only.

    Models may retain the canonical source ID after reading an excerpt. Binding
    it to the actual visible reads avoids another read without granting the
    hidden source body or changing downstream evidence scope.
    """
    resolved = []
    for task_id in dependencies:
        source = view.get(task_id, {})
        candidates = []
        if source.get('content_scope') == 'index_only' and source.get('source_version'):
            for read_id, result in view.items():
                if result.get('content_scope') in ('index_only', 'shared_result') or not result.get('result'):
                    continue
                if any(read.get('source_task_id') == task_id
                       and read.get('source_version') == source['source_version']
                       and 0 <= read.get('start_char', -1) < read.get('end_char', -1)
                       for read in result.get('result_reads') or []):
                    candidates.append(read_id)
        for dependency in candidates or [task_id]:
            if dependency not in resolved:
                resolved.append(dependency)
    return resolved


def answer_source_scope(view, dependencies):
    """Backend-derived scope from the exact model view, not all stored results."""
    scope = {}
    for tid in dependencies:
        result = view.get(tid, {})
        if result.get('content_scope') == 'index_only':
            continue
        reads = result.get('result_reads')
        for citation in result.get('citations') or []:
            cid = str(citation['id'])
            inherited = (result.get('evidence_scope') or {}).get(cid)
            if inherited is not None:
                if inherited.get('full'):
                    scope[cid] = {'full': True}
                elif not scope.get(cid, {}).get('full'):
                    scope.setdefault(cid, {'reads': []})['reads'].extend(inherited.get('reads') or [])
                continue
            if not reads:
                # An alias has no body; its visible owner supplies the scope.
                if result.get('content_scope') != 'shared_result':
                    scope[cid] = {'full': True}
            elif not scope.get(cid, {}).get('full'):
                scope.setdefault(cid, {'reads': []})['reads'].extend(
                    read for read in reads if cid in read['citation_ids'])
    # A Main artifact can depend on two artifacts with the same source range.
    # Keep a set union so repeated derivations cannot multiply lineage metadata.
    for value in scope.values():
        if not value.get('full'):
            unique = {}
            for read in value.get('reads') or []:
                key = tuple(read.get(field) for field in ('source_task_id', 'source_version', 'field', 'start_char', 'end_char'))
                unique.setdefault(key, read)
            value['reads'] = list(unique.values())
    return scope


def scoped_source_text(state, scope):
    pieces = []
    for read in scope.get('reads', []):
        source = (state.get('task_results') or {}).get(read['source_task_id'])
        if not source or result_version(source) != read['source_version']:
            raise ValueError('已读取证据的来源版本不一致')
        field = read['field']
        if field.startswith('citation:'):
            cid = field.split(':', 1)[1]
            text = (source.get('citation_contents') or {}).get(cid)
            if text is None:
                text = next((c.get('excerpt') or '' for c in source.get('citations') or []
                             if str(c['id']) == cid), '')
        else:
            text = source.get('result') or ''
        if not (0 <= read['start_char'] <= read['end_char'] <= len(text)):
            raise ValueError('已读取证据的范围不合法')
        piece = text[read['start_char']:read['end_char']]
        if piece not in pieces:
            pieces.append(piece)
    return '\n\n'.join(pieces)
