"""The Java article service owns HTML sanitation and article persistence."""
import hashlib

import httpx
from markdown_it import MarkdownIt

from app.config import settings


class DraftConflict(ValueError):
    """A safe user-facing conflict; never retry with a freshly fetched lock automatically."""


def render_draft(draft):
    if getattr(draft, "content_format", "markdown") == "html":
        # Only manual edits select HTML; Java sanitizes at persistence.
        # Generated Markdown retains HTML-disabled rendering below.
        return draft.content
    return MarkdownIt("commonmark", {"html": False}).enable("table").render(draft.content)


def draft_hash(draft, html):
    hasher = hashlib.sha256()
    for field in (draft.title, draft.summary, draft.content, html):
        value = field.encode()
        hasher.update(len(value).to_bytes(4, "big"))
        hasher.update(value)
    return hasher.hexdigest()


async def save_approved_draft(state, draft):
    body = {"runId": state["run_id"], "executionToken": state["execution_token"],
            "articleId": str(state["pending_article_id"]), "title": draft.title,
            "summary": draft.summary, "markdown": draft.content, "html": state["draft_html"],
            "draftHash": state["draft_hash"],
            "baseDraftHash": state.get('approved_base_hash') or state['draft_hash'],
            "expectedRevisionId": (state.get('target_draft') or {}).get('revision_id'),
            "expectedLockVersion": (state.get('target_draft') or {}).get('lock_version')}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(settings.JAVA_AGENT_URL.rstrip("/") + "/internal/agent/drafts",
            headers={"X-Agent-Key": settings.AGENT_SERVICE_KEY, "X-Agent-User": str(state["user_id"])}, json=body)
        if response.status_code == 409:
            raise DraftConflict("草稿内容或审核状态已变化，请重新读取最新草稿后再生成并确认保存；本次未覆盖原文。")
        response.raise_for_status()
        return int(response.json()["articleId"])
