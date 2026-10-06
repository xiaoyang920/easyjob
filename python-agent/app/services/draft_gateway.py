"""The Java article service owns HTML sanitation and article persistence."""
import hashlib

import httpx
from markdown_it import MarkdownIt

from app.config import settings


def render_draft(draft):
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
            "draftHash": state["draft_hash"]}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(settings.JAVA_AGENT_URL.rstrip("/") + "/internal/agent/drafts",
            headers={"X-Agent-Key": settings.AGENT_SERVICE_KEY, "X-Agent-User": str(state["user_id"])}, json=body)
        response.raise_for_status()
        return int(response.json()["articleId"])
