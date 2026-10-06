"""Private history retrieval; never article evidence or a memory-writing tool."""
import json

from app.security.capabilities import require_capability
from app.services.memory import memory_service


async def retrieve_memory(state: dict) -> dict:
    require_capability(state, "memory_read")
    if not isinstance(state.get("user_id"), int) or state["user_id"] <= 0:
        raise PermissionError("记忆召回必须绑定可信用户")
    task = state["current_task"]
    # The graph context is server-built. Neither query text nor model fields
    # provide user identity, collection names, SQL filters or top_k.
    recalled = await memory_service.recall_details(state["user_id"], task["instruction"], top_k=3, strict=True,
                                                   conversation_id=state.get("conversation_id"), include_profile=False)
    memories = recalled["memories"]
    sources = [{"id": f"memory:{m['memory_id']}", "type": m.get("memory_type", "decision"),
                "scope": m.get("scope", "user"), "key": m.get("memory_key"),
                "source_conversation_id": str(m["source_conversation_id"]) if m.get("source_conversation_id") is not None else None}
               for m in memories]
    found = bool(memories)
    text = json.dumps({"notice": "当前用户的有效已确认决策候选，不是公开事实证据；当前用户指示优先。",
                       "memories": [{"source_id": f"memory:{m['memory_id']}", "content": m["content"],
                                     "type": m.get("memory_type", "decision"), "scope": m.get("scope", "user"),
                                     "key": m.get("memory_key")} for m in memories],
                       "lookup_message": "未找到相关已确认决策。" if not memories else "已召回相关已确认决策。"}, ensure_ascii=False)
    # A completed empty lookup is still a successful operation. Main sees the
    # explicit miss; it must not fabricate a recollection or spend recovery budget.
    return {"status": "succeeded", "result": text, "citations": [], "article_cards": [],
            "memory_sources": sources, "memory_found": found, "memory_match_count": len(memories)}
