"""Literal lookup plans with bounded, version-bound continuation cursors."""
import base64
from dataclasses import dataclass
import hashlib
from itertools import islice
import json
import re

from app.utils.context_budget import json_text


def sections(text, limit=32):
    """Only explicit Markdown ATX headings outside fenced code are indexed."""
    result, stack, offset, fence, total = [], [], 0, None, 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
        elif fence is None and (match := re.match(r'^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$', line)):
            level = len(match[1])
            while stack and stack[-1]['level'] >= level:
                stack.pop()['end_char'] = offset
            total += 1
            if len(result) < limit:
                item = {'section_id': f'h_{offset}', 'title': match[2][:120],
                        'level': level, 'start_char': offset, 'end_char': len(text)}
                result.append(item)
                stack.append(item)
        offset += len(line)
    return result, total > limit


def cursor_encode(binding, position):
    raw = json_text({**binding, 'position': position}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def cursor_decode(value, binding, total):
    try:
        if len(value) > 2048:
            raise ValueError()
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        payload = json.loads(raw)
        position = payload.pop('position')
        if payload != binding or type(position) is not int or not 0 <= position <= total:
            raise ValueError()
        return position
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise ValueError('读取游标无效或来源/定位条件已变化，请重新定位') from exc


@dataclass
class Selection:
    task_id: str
    source: dict
    args: dict
    text: str
    field: str
    citations: list
    version: str
    binding: dict
    start: int
    end: int
    matches: list | None

    @property
    def demand(self):
        if self.matches == []:
            return 0
        return min(self.args.get('max_chars', 12000), self.end - self.start)


def locate(task_id, source, args):
    from app.services.result_access import result_version
    text, field = source.get('result') or '', 'result'
    citations = source.get('citations') or []
    cid = args.get('citation_id')
    if cid:
        citations = [c for c in citations if str(c['id']) == cid]
        if not citations:
            raise ValueError('引用不属于指定任务结果')
        canonical = (source.get('citation_contents') or {}).get(cid)
        if canonical is None:
            canonical = citations[0].get('excerpt')
            if not canonical or canonical not in text:
                raise ValueError('结果缺少可定位的引用正文，请按关键词或字符读取')
        text, field = canonical, 'citation:' + cid
    version = result_version(source)
    words = args.get('queries') or ([args['query']] if args.get('query') else [])
    locator = {'words': sorted(set(words)), 'citation_id': cid, 'section_id': args.get('section_id')}
    binding = {'v': 1, 'task': task_id, 'version': version, 'field': field,
               'locator': hashlib.sha256(json_text(locator).encode()).hexdigest()}
    start, end = args.get('start_char', 0), len(text)
    if args.get('section_id'):
        available, _ = sections(text)
        section = next((item for item in available if item['section_id'] == args['section_id']), None)
        if section is None:
            raise ValueError('章节不存在于当前来源目录')
        start, end = section['start_char'], section['end_char']
    if args.get('cursor'):
        position = cursor_decode(args['cursor'], binding, len(text))
        if not start <= position <= end:
            raise ValueError('读取游标不在指定章节范围内')
        start = position
    if start > len(text) or (start == len(text) and start != 0 and not args.get('cursor')):
        raise ValueError('读取起点超出结果范围')
    matches = None
    if words:
        pattern = re.compile('|'.join(re.escape(word) for word in sorted(set(words), key=len, reverse=True)), re.IGNORECASE)
        matches = [(m.start(), m.end()) for m in islice(pattern.finditer(text, start, end), 4)]
    return Selection(task_id, source, args, text, field, citations, version, binding, start, end, matches)
