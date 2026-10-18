"""Public execution events: observable work, never prompts or model reasoning."""
import logging

from langchain_core.callbacks.manager import adispatch_custom_event
from langgraph.config import get_config

log = logging.getLogger(__name__)


async def publish_event(payload):
    try:
        config = get_config()
    except RuntimeError:
        return  # Also used by services outside a streamed graph.
    try:
        await adispatch_custom_event("agent_event", {"version": 1, **payload}, config=config)
    except Exception:
        log.debug("Public activity event unavailable", exc_info=True)


async def activity(state, step, label, status="active", detail=""):
    task_id = state.get("task_id", "")
    owner = task_id or f"main/round_{state.get('main_round', 0)}"
    await publish_event({"kind": "activity", "id": f"{owner}/{step}",
        "taskId": task_id, "step": step, "label": label, "status": status, "detail": detail,
        "actor": "subagent" if state.get("execution_mode") == "delegate" and task_id else "main"})


async def node_activity(state, node, status):
    labels = {"main_agent": "理解请求", "planner": "调整任务计划", "main_retrieve": "检索相关资料",
        "main_answer": "整理检索结果", "main_task": "执行任务", "generate_draft": "生成草稿",
        "approve_draft": "等待确认草稿", "save_draft": "保存草稿", "synthesizer": "整理最终回答",
        "reject_draft": "放弃草稿保存", "main_delegate": "执行委派任务",
        "prepare_draft": "准备草稿资料", "collect_draft": "完成草稿处理",
        "final_gate": "核对引用与来源"}
    if node not in labels:
        return
    if node == "main_agent":
        labels[node] = "整理草稿处理结果" if state.get("business_complete") else "根据结果决定下一步" if state.get("main_round") else "理解请求"
        state = {**state, "main_round": state.get("main_round", 0) + 1}
    if node == "main_retrieve" and any(t.get("retrieval_target") == "memory" for t in state.get("plan", {}).get("tasks", [])):
        labels[node] = "召回相关记忆"
    task = state.get("current_task", {})
    label = {"search": "检索资料", "analysis": "分析资料"}.get(task.get("kind"), labels[node]) if node == "main_task" else labels[node]
    await activity(state, "task" if node == "main_task" else node, label, status)


async def publish_route(state, action, plan_update=None):
    texts = {"answer": "我会直接回答这个问题。", "retrieve": "我会先检索相关资料，核对来源后给出回答。",
        "delegate": "我会把需要独立处理的任务交给子代理，再根据结果继续处理。",
        "write_draft": "我会生成草稿，核对来源后请你确认保存。"}
    if action == "retrieve" and plan_update and plan_update["plan"]["tasks"][0].get("retrieval_target") == "memory":
        texts[action] = "我会先查找相关历史记忆，再根据结果继续处理。"
    await publish_event({"kind": "commentary", "text": texts[action], "mode": action})
    if plan_update:
        tasks = plan_update["plan"]["tasks"]
        stages = {tid: i + 1 for i, stage in enumerate(plan_update["stages"]) for tid in stage}
        await publish_event({"kind": "plan", "mode": action, "tasks": [
            {"id": t["task_id"], "label": t["instruction"],
             "role": "memory" if t.get("retrieval_target") == "memory" else t["kind"],
             "stage": stages[t["task_id"]], "dependsOn": t["depends_on"]} for t in tasks]})
