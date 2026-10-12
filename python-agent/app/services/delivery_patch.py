"""Apply bounded paragraph edits while retaining untouched text byte for byte."""
import json
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParagraphReplacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    block_index: int = Field(ge=0, description='后端提供的原文分段编号')
    issue_block_index: int = Field(ge=0, description='本段修正所对应的问题段编号；关联段也必须指向真实问题')
    text: str = Field(min_length=1, max_length=100000,
        description='替换这一完整段落；草稿标题和摘要只填字段正文，不加title/summary标签')

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('修正段落不能为空白')
        return value


class GroundingPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    replacements: list[ParagraphReplacement] = Field(min_length=1, max_length=80)


def paragraph_spans(text):
    """Match grounding.paragraphs, including blank lines inside fenced code."""
    spans, start, end, offset, fence = [], None, 0, 0, ''
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip('\r\n')
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ''
        if not line.strip() and not fence:
            if start is not None:
                spans.append((start, end))
                start = None
        else:
            if start is None:
                start = offset
            end = offset + len(line)
        offset += len(raw)
    if start is not None:
        spans.append((start, end))
    return spans


def apply_delivery_patch(text, patch, issues):
    from app.services.grounding import draft_payload, text_blocks
    patch = GroundingPatch.model_validate(patch)
    blocks = text_blocks(text)
    issue_indices = {issue['block_index'] for issue in issues
                     if isinstance(issue, dict) and isinstance(issue.get('block_index'), int)}
    # Backend execution mismatches can be detected before semantic segmentation.
    if not issue_indices:
        issue_indices = set(range(len(blocks)))
    edits = {}
    for edit in patch.replacements:
        if edit.block_index >= len(blocks) or edit.block_index in edits or edit.issue_block_index not in issue_indices:
            raise ValueError('修正段落编号重复、越界或未关联实际问题')
        edits[edit.block_index] = edit.text
    if not issue_indices <= edits.keys():
        raise ValueError('修正遗漏实际问题段落')
    payload = draft_payload(text)
    body = payload['content'] if payload is not None else text
    shift = 2 if payload is not None else 0
    spans = paragraph_spans(body)
    if len(spans) + shift != len(blocks):
        raise ValueError('修正段落与原文不一致')
    for index in sorted(edits, reverse=True):
        if index < shift:
            payload['title' if index == 0 else 'summary'] = edits[index]
        else:
            start, end = spans[index - shift]
            body = body[:start] + edits[index] + body[end:]
    if payload is not None:
        payload['content'] = body
        return json.dumps(payload, ensure_ascii=False)
    if draft_payload(body) is not None:
        raise ValueError('局部修正改变了回答与草稿的输出格式')
    return body
