"""Private draft reads use Java's owner checks, never the public search index."""
import json

import httpx

from app.config import settings
from app.security.capabilities import require_capability
from app.utils.token_utils import count_tokens


async def retrieve_drafts(state):
    require_capability(state, "own_draft_read")
    task = state["current_task"]
    ids = task.get("article_ids", [])
    headers = {"X-Agent-Key": settings.AGENT_SERVICE_KEY, "X-Agent-User": str(state["user_id"])}
    async with httpx.AsyncClient(timeout=20) as client:
        path = f"/internal/agent/drafts/{ids[0]}" if ids else "/internal/agent/drafts"
        response = await client.get(settings.JAVA_AGENT_URL.rstrip("/") + path, headers=headers,
                                    params={} if ids else {"keyword": task.get("search_query") or ""})
    if response.status_code in (403, 404):
        return {"status": "succeeded", "result": "未找到可读取的本人草稿；不能使用猜测的文章ID。",
                "citations": [], "article_cards": []}
    if response.status_code >= 500:
        # Return a recoverable tool_error through the action loop, without
        # leaking internal response details or falling back to public search.
        raise ConnectionError("Private draft service unavailable")
    response.raise_for_status()
    data = response.json()
    if not ids:
        return {"status": "succeeded", "result": "本人草稿列表（需按真实articleId读取正文后才能修改）：\n" + json.dumps(data, ensure_ascii=False),
                "citations": [], "article_cards": []}
    content = data['payload'].get('content') or ''
    document = {"article_id": str(data["articleId"]), "revision_id": str(data["revisionId"]),
                "lock_version": int(data["lockVersion"]), "state": data["state"],
                "editable": bool(data["editable"]), "title": data["payload"]["title"],
                "summary": data["payload"].get("summary") or "", "content": content,
                "content_type": data['payload'].get('contentType') or 1}
    rendered = "本人草稿当前工作版本（私有资料，不是公共事实证据）：\n" + json.dumps(document, ensure_ascii=False)
    # Bound the actual serialized input, including escaped code/newlines. Never
    # silently rewrite a document whose tail was dropped from context.
    if len(rendered) > settings.TASK_RESULT_MAX_CHARS or count_tokens(rendered) > settings.WORKER_OUTPUT_MAX_TOKENS:
        return {"status": "insufficient_evidence",
                "result": "草稿过长，请在文章编辑器中修改；未载入全文，不启动覆盖保存。",
                "citations": [], "article_cards": []}
    return {"status": "succeeded", "result": rendered,
            "draft_document": document, "citations": [], "article_cards": []}
