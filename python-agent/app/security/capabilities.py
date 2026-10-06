"""Server policy grants capabilities; model requests and skills cannot grant them."""
from app.config import settings


def task_capabilities(task) -> frozenset[str]:
    # Role names choose an executor, not a permission. Both Main and delegated
    # retrieval use the same policy; analysis has no tool capabilities.
    if task.kind == "search" and task.retrieval_target == "memory":
        return frozenset({"memory_read"})
    allowed = {"search": {"platform_read"}, "analysis": set(), "writing": {"draft_generate"}}[task.kind]
    if task.allow_web and task.kind != "search":
        raise PermissionError("当前任务不能请求联网能力")
    if task.kind == "search" and task.allow_web and settings.AGENT_WEB_SEARCH_ENABLED:
        allowed.add("web_search")
    return frozenset(allowed)


def effective_capabilities(state) -> frozenset[str]:
    from app.graph.staged_plan import load_execution_task
    if not state.get("current_task"):
        raise PermissionError("缺少服务端执行上下文")
    expected_actor = "subagent" if state.get("execution_mode") == "delegate" else "main"
    task = load_execution_task(state["current_task"], expected_actor)
    allowed = task_capabilities(task)
    # A structured user rule can narrow access, never grant a server-disabled tool.
    if any(c.get("key") == "web_search" and c.get("content") == "deny" for c in state.get("active_constraints", [])
           if c.get("id") not in state.get("constraint_overrides", [])):
        allowed = allowed - {"web_search"}
    # Old checkpoints may predate grants. Current policy still applies;
    # persisted grants can narrow, never expand it after a policy change.
    granted = state.get("capabilities")
    return allowed if granted is None else allowed.intersection(granted)


def require_capability(state, capability: str):
    if capability not in effective_capabilities(state):
        raise PermissionError(f"执行上下文未获授 {capability} 能力")


def require_draft_approval(state):
    require_capability(state, "draft_generate")
    if state.get("decision") != "approve":
        raise PermissionError("用户批准当前版本后才能保存草稿")
    # Local workflow gate only. The gateway still checks the authenticated
    # owner, live execution token and approved content hash.
