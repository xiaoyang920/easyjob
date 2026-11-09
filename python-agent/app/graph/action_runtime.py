"""Read-only actions return observations; approval is a separate durable boundary."""
import asyncio

import httpx
from elastic_transport import ConnectionError as EsConnectionError
from openai import APIConnectionError
from langgraph.types import Send

from app.config import settings
from app.graph import staged_runtime as runtime
from app.graph.staged_plan import load_execution_plan, merge_task_results
from app.services.agent_events import activity
from app.services.task_artifacts import task_artifacts, task_fingerprint
from app.services.tool_recovery import ToolTaskError
from app.services.tool_registry import tool_registry
from app.security.capabilities import require_capability
from app.rpc.blog_client import ServiceError

RECOVERABLE = (TimeoutError, ConnectionError, httpx.RequestError, APIConnectionError, EsConnectionError)


def failed_result(task, status, message):
    return {"task_id": task.task_id, "kind": task.kind, "actor": task.actor, "instruction": task.instruction,
            "retrieval_target": task.retrieval_target,
            "status": status, "result": message, "citations": [], "article_cards": [],
            "draft_article_id": None, "draft_title": ""}


def observe(state, results):
    failures = {tid: r["status"] for tid, r in results.items() if r["status"] != "succeeded"}
    if any(status not in ("insufficient_evidence", "tool_error", "blocked", "invalid_citation") for status in failures.values()):
        raise ValueError("局部修正后结果仍不符合引用要求")
    return {"task_results": results, "observations": [*state.get("observations", []),
                {"round": state["main_round"], "action": state["main_action"],
                 "tasks": {tid: r["status"] for tid, r in results.items()},
                 "retrieval_reports": {tid: r["retrieval_report"] for tid, r in results.items() if r.get("retrieval_report")},
                 "tool_failures": {tid: r["tool_failure"] for tid, r in results.items() if r.get("tool_failure")},
                 "failures": failures}],
            "correction_count": state.get("correction_count", 0) + bool(failures)}


def current_task(state):
    return load_execution_plan(state["plan"], "main").tasks[0]


async def execute_tool_node(state):
    task = current_task(state)
    if task.kind not in ('search', 'tool'):
        raise PermissionError('通用工具入口仅接受 Main 的只读工具任务')
    if task.tool_name is None:
        # Old persisted graph tasks only; new MainDecision never accepts retrieve.
        from app.graph.main_agent import RetrievalRequest
        from app.models.main_tool import call_from_retrieval, task_fields
        from app.graph.staged_plan import ExecutionTask
        request = RetrievalRequest(target=task.retrieval_target, task_id=task.task_id,
            **task.model_dump(include={'instruction', 'allow_web', 'article_ids', 'required_skills',
                                      'filters', 'search_query', 'editor_part', 'urls'}))
        task = ExecutionTask(task_id=task.task_id, actor='main', **task_fields(call_from_retrieval(request)))
    spec = tool_registry.main_tool(task.tool_name)
    context = runtime.task_context(state, task)
    # The rewrite layer chooses complete turns by Token budget; preserve the
    # separate summary here rather than removing it with a message-count slice.
    context["history_messages"] = list(state.get("history_messages", []))
    if task.tool_name in ('read_task_result', 'read_task_results'):
        context['readable_task_results'] = state.get('task_results') or {}
    memory_lookup = task.retrieval_target == "memory"
    editor_lookup = task.retrieval_target == 'editor'
    label = spec.label
    require_capability(context, spec.capability)
    await runtime.assert_run(context)
    await activity(context, "task", label)
    try:
        evidence = await asyncio.wait_for(spec.handler(context), 120)
        update = {"worker_results": [{"worker_name": "search", "status": evidence["status"],
                    "result": evidence.get("rag_context") or evidence.get("result") or "未找到可用资料。"}],
                  "citations": evidence["citations"], "article_cards": evidence["article_cards"]}
        if evidence.get("retrieval_report"):
            update["retrieval_report"] = evidence["retrieval_report"]
        if evidence.get('citation_contents'):
            update['citation_contents'] = evidence['citation_contents']
        if 'result_reads' in evidence:
            update['result_reads'] = evidence['result_reads']
        if 'result_access_metrics' in evidence:
            update['result_access_metrics'] = evidence['result_access_metrics']
        if 'evidence_scope' in evidence:
            update['evidence_scope'] = evidence['evidence_scope']
        if evidence.get('draft_document'):
            update['draft_document'] = evidence['draft_document']
        if editor_lookup:
            update.update({k: evidence[k] for k in ('editor_snapshot_id', 'editor_part') if k in evidence})
        if memory_lookup:
            update.update({k: evidence[k] for k in ("memory_sources", "memory_found", "memory_match_count")})
        result = runtime.task_result(context, update, raw_retrieval=spec.raw_evidence)
    except ToolTaskError as exc:
        result = {**failed_result(task, "tool_error", str(exc)), "tool_failure": exc.report}
    except ServiceError as exc:
        if exc.status in (401, 403, 409):
            raise PermissionError('工具服务拒绝访问，不能自动扩大权限重试') from None
        result = {**failed_result(task, 'tool_error', '工具服务暂时不可用，可调整参数后重试。'),
                  'tool_failure': {'code': 'TOOL_UNAVAILABLE', 'tool': task.tool_name}}
    except RECOVERABLE:
        result = {**failed_result(task, 'tool_error', '工具服务暂时不可用，可调整参数或稍后重试。'),
                  'tool_failure': {'code': 'TOOL_UNAVAILABLE', 'tool': task.tool_name}}
    except ValueError:
        from app.services.context_projection import CONTEXT_READ_TOOLS
        if task.tool_name not in CONTEXT_READ_TOOLS: raise
        result = failed_result(task, 'tool_error', '回查范围无效或资料版本已变化，请使用当前会话的真实编号或重新读取原资料。')
    await runtime.assert_run(state)
    await activity(context, "task", label, "done" if result["status"] == "succeeded" else "error")
    result['tool_name'] = task.tool_name
    return {**observe(state, {task.task_id: result}), "retrieval_status": result["status"] if task.kind == 'search' else state.get('retrieval_status', '')}


# Compatibility entry for checkpoints paused at the old node, never a new route.
main_retrieve_node = execute_tool_node


async def run_subagent(context, task):
    fingerprint = task_fingerprint(context) if context.get('run_id') else None
    if fingerprint:
        cached = await task_artifacts.load(context, fingerprint)
        if cached is not None:
            await runtime.assert_run(context)
            await activity(context, 'task', '复用已完成子任务', 'done')
            return {task.task_id: cached}
    try:
        result = (await runtime.subagent_node(context))["task_results"]
    except ToolTaskError as exc:
        await runtime.assert_run(context)
        result = {task.task_id: {**failed_result(task, "tool_error", str(exc)), "tool_failure": exc.report}}
    except RECOVERABLE:
        # Cancellation, permissions, stale sources and persistence errors propagate.
        await runtime.assert_run(context)
        result = {task.task_id: failed_result(task, "tool_error", "只读任务服务暂时不可用。")}
    if fingerprint:
        await task_artifacts.save(context, fingerprint, result[task.task_id], runtime.executor_token(context))
    return result


async def main_delegate_node(state):
    plan = load_execution_plan(state["plan"], "subagent")
    completed = dict(state.get("task_results") or {})
    outputs, running = {}, {}
    pending = {t.task_id: t for t in plan.tasks}
    try:
        while pending or running:
            await runtime.assert_run(state)
            for tid, task in list(pending.items()):
                # Unaffected branches continue; dependent branches never consume failures.
                if any(dep in completed and completed[dep]["status"] != "succeeded" for dep in task.depends_on):
                    result = failed_result(task, "blocked", "必需依赖未成功，此任务未执行。")
                    completed[tid] = outputs[tid] = result
                    del pending[tid]
                    await activity({**state, "task_id": tid}, "task", "依赖未满足", "error")
                elif len(running) < settings.SUBAGENT_CONCURRENCY and all(dep in completed for dep in task.depends_on):
                    context = runtime.task_context({**state, "task_results": completed}, task)
                    running[asyncio.create_task(run_subagent(context, task))] = tid
                    del pending[tid]
            if not running:
                if pending:
                    # A blocked result may unlock propagation in the next iteration.
                    if any(all(dep in completed for dep in t.depends_on) for t in pending.values()):
                        continue
                    raise ValueError("任务依赖无法就绪")
                break
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                tid = running.pop(future)
                result = await future
                if result[tid]['status'] == 'invalid_citation':
                    task = next(task for task in plan.tasks if task.task_id == tid)
                    # A rejected local artifact is an observation, not a valid
                    # dependency or an exception that cancels independent work.
                    result = {tid: failed_result(task, 'invalid_citation',
                              '局部引用修正未通过，此产物不可用，请调整策略。')}
                completed = merge_task_results(completed, result)
                outputs.update(result)
    finally:
        for future in running:
            future.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
    return observe(state, outputs)


def prepare_draft(state):
    # Materialize/validate all dependencies before reaching the side-effect subgraph.
    task = current_task(state)
    if task.kind != "writing":
        raise PermissionError("草稿流程仅接受主代理写作请求")
    runtime.task_context(state, task)
    return {}


def draft_dispatcher(state):
    return [Send("writing_worker", runtime.task_context(state, current_task(state)))]


def collect_draft(state):
    result = state["task_results"][state["action_task_ids"][0]]
    if result["status"] != "succeeded":
        raise ValueError("草稿业务流程未完成")
    return {"business_complete": True, "draft_article_id": result["draft_article_id"],
            "worker_results": [{"worker_name": "writing", "result": result["result"],
                                "draft_article_id": result["draft_article_id"], "draft_title": result["draft_title"]}],
            "observations": [*state.get("observations", []), {"round": state["main_round"],
                "action": "write_draft", "tasks": {result["task_id"]: "succeeded"}}]}
