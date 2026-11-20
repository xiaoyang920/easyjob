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
    labels = {"main_agent": "理解请求", "planner": "调整任务计划", "main_retrieve": "检索相关资料", "execute_tool": "调用工具",
        "main_answer": "整理检索结果", "main_task": "执行任务", "generate_draft": "生成草稿",
        "verify_draft": "核验草稿依据", "plan_draft_lookup": "补充草稿资料", "lookup_draft_evidence": "检索草稿缺失资料",
        "approve_draft": "等待确认草稿", "save_draft": "保存草稿", "synthesizer": "整理最终回答",
        "reject_draft": "放弃草稿保存", "main_delegate": "执行委派任务",
        "prepare_draft": "准备草稿资料", "collect_draft": "完成草稿处理",
        "final_gate": "核对引用与来源"}
    if node not in labels:
        return
    if node == 'final_gate' and state.get('browser_session_id'):
        labels[node] = '完成本轮回复'
    if node == "main_agent":
        labels[node] = "整理草稿处理结果" if state.get("business_complete") else "根据结果决定下一步" if state.get("main_round") else "理解请求"
        state = {**state, "main_round": state.get("main_round", 0) + 1}
    if node == "main_retrieve" and any(t.get("retrieval_target") == "memory" for t in state.get("plan", {}).get("tasks", [])):
        labels[node] = "召回相关记忆"
    if node == 'execute_tool':
        from app.services.tool_registry import tool_registry
        task = next(iter(state.get('plan', {}).get('tasks', [])), {})
        if task.get('tool_name'):
            spec = tool_registry.main_tool(task['tool_name'])
            if spec.capability == 'browser_control':
                return  # The executor already publishes the tool's activity under its task ID.
            labels[node] = spec.label
    task = state.get("current_task", {})
    label = {"search": "检索资料", "analysis": "分析资料"}.get(task.get("kind"), labels[node]) if node == "main_task" else labels[node]
    await activity(state, "task" if node == "main_task" else node, label, status)


async def publish_task_result(task_id, result):
    status = result['status']
    failure_notes = {
        'blocked': '依赖任务未成功，这一步没有执行。',
        'tool_error': '工具未能返回可用结果。',
        'insufficient_evidence': '这次没有找到可用的候选资料。',
        'invalid_citation': '结果未通过引用校验，暂不用于回答。',
    }
    if result.get('browser_outcome'):
        text = result['result']
    elif status != 'succeeded':
        text = failure_notes.get(status, '这一步未完成。')
    elif 'result_reads' in result:
        reads = result['result_reads'] or []
        count = len({read['source_task_id'] for read in reads})
        text = f'已读取 {count} 份任务结果中的相关片段。' if count else '在指定范围内没有读到匹配片段。'
    elif result.get('retrieval_target') == 'memory':
        text = '找到了相关的历史记忆。' if result.get('memory_found') else '没有找到匹配的历史记忆。'
    elif result.get('retrieval_target') in ('drafts', 'editor'):
        text = '已取得当前文档的读取结果。'
    elif result.get('kind') == 'search' and result.get('citations'):
        text = f'取得 {len(result["citations"])} 条候选来源，等待后续判断。'
    elif result.get('kind') == 'analysis':
        text = '已完成资料分析，结果可用于后续整理。'
    else:
        text = '已取得工具返回的资料。'
    await publish_event({'kind': 'result', 'id': f'{task_id}/result', 'taskId': task_id, 'text': text})


async def publish_route(state, action, plan_update=None, *, progress_note=None):
    texts = {"answer": "我会直接回答这个问题。", "retrieve": "我会先检索相关资料，核对来源后给出回答。",
        "call_tool": "我会读取所需资料，再根据结果继续处理。",
        "delegate": "我会把需要独立处理的任务交给子代理，再根据结果继续处理。",
        "write_draft": "我会生成草稿，核对来源后请你确认保存。"}
    if action == 'answer' and state.get('task_results'):
        texts[action] = "我会根据已有结果整理回答。"
    if action == "retrieve" and plan_update and plan_update["plan"]["tasks"][0].get("retrieval_target") == "memory":
        texts[action] = "我会先查找相关历史记忆，再根据结果继续处理。"
    if action == 'call_tool' and plan_update:
        from app.services.tool_registry import tool_registry
        task = plan_update['plan']['tasks'][0]
        spec = tool_registry.main_tool(task['tool_name'])
        texts[action] = f'我会先{spec.label}，再根据结果继续处理。'
    note = ' '.join(progress_note.split()) if progress_note else ''
    owner = plan_update['plan']['tasks'][0]['task_id'] if plan_update else f"main/round_{state.get('main_round', 0) + 1}"
    await publish_event({"kind": "commentary", "id": f"{owner}/route",
                         "text": note or texts[action], "mode": action})
    if plan_update:
        tasks = plan_update["plan"]["tasks"]
        stages = {tid: i + 1 for i, stage in enumerate(plan_update["stages"]) for tid in stage}
        await publish_event({"kind": "plan", "mode": action, "tasks": [
            {"id": t["task_id"], "label": t["instruction"],
             "role": "memory" if t.get("retrieval_target") == "memory" else t["kind"],
             "stage": stages[t["task_id"]], "dependsOn": t["depends_on"]} for t in tasks]})
