"""Shared dependency, fencing and citation guards; isolated read-only Subagents."""
import asyncio
import json
import re
import time
import inspect

from langgraph.config import get_config
from langgraph.errors import GraphInterrupt

from app.graph.staged_plan import ExecutionTask, load_execution_task
from app.graph.nodes.search_worker import search_worker_node
from app.graph.nodes.analysis_worker import analysis_worker_node
from app.services.run_repository import run_repository
from app.services.evidence_verifier import verify_public_evidence
from app.services.agent_events import activity, node_activity
from app.security.capabilities import task_capabilities
from app.config import settings
from app.utils.context_budget import ContextBudgetExceeded, input_budget
from app.utils.token_utils import count_tokens
from app.models.memory_overlay import turn_memory_context


def result_view(state, task_id, result):
    """Normalize legacy result metadata without replacing immutable outcomes."""
    actor = result.get("actor")
    if actor is None:
        action = next((entry["action"] for entry in state.get("action_history", [])
                       if task_id in entry.get("task_ids", [])), "delegate")
        actor = "subagent" if action == "delegate" else "main"
    kind = result.get("kind", result.get("subagent"))
    return {**{k: v for k, v in result.items() if k != "subagent"}, "kind": kind, "actor": actor,
            "retrieval_target": result.get("retrieval_target", "knowledge" if kind == "search" else None)}


def task_context(state, task):
    turn_context = turn_memory_context(state)
    task = ExecutionTask.model_validate(task)
    results = state.get("task_results") or {}
    dependencies = {}
    for dep in task.depends_on:
        result = results.get(dep)
        if not result or result["status"] != "succeeded":
            raise ValueError("必需依赖缺失或未成功")
        dependencies[dep] = result_view(state, dep, result)
    assessment = (state.get('main_decision') or {}).get('evidence_assessment')
    if assessment is not None and task.actor == 'main' and task.kind in ('analysis', 'writing'):
        # Main-authored artifacts/drafts inherit only its chosen sources. Do not
        # mutate stored results or pre-judge new sources inside a delegated DAG.
        selected = set(assessment['selected_ids'])
        for dep, result in list(dependencies.items()):
            citations = [c for c in result.get('citations', []) if str(c['id']) in selected]
            articles = {str(c.get('articleId')) for c in citations if c.get('articleId')}
            filtered = {**result, 'citations': citations, 'article_cards': [
                card for card in result.get('article_cards', []) if str(card['articleId']) in articles]}
            if result.get('retrieval_report', {}).get('assessment_owner') == 'main':
                contents = result.get('citation_contents', {})
                filtered['result'] = '\n\n'.join(
                    f"[{c['id']}] {c.get('title', '')}\n{contents.get(str(c['id']), c.get('excerpt', ''))}" for c in citations)
            dependencies[dep] = filtered
    for result in dependencies.values():
        # Internal source storage must not duplicate full chunks in model inputs.
        result.pop('citation_contents', None)
    evidence = {}
    for result in dependencies.values():
        for citation in result.get("citations", []):
            cid = str(citation["id"])
            if cid in evidence and evidence[cid] != citation:
                raise ValueError("依赖引用编号存在冲突证据")
            evidence[cid] = citation
    if task.requires_evidence and task.kind in ("analysis", "writing") and not evidence:
        raise ValueError("必需证据缺失")
    return {
        "user_id": state["user_id"], "run_id": state.get("run_id", ""),
        "execution_token": state.get("execution_token", ""),
        "conversation_id": state.get("conversation_id"),
        "origin_article_id": state.get("origin_article_id"),
        "article_context": state.get("article_context", {}),
        "task_id": task.task_id, "current_task": task.model_dump(),
        "user_message": task.instruction, "task_descriptions": {task.kind: task.instruction},
        "request_goal": state["user_message"] if task.actor == "main" else task.instruction,
        "required_skills": task.required_skills, "history_messages": [], "memory_context": "",
        "user_profile": turn_context['user_profile'] if task.actor == "main" else {},
        "active_constraints": [c for c in turn_context['active_constraints'] if c["id"] not in state.get("constraint_overrides", [])],
        "dependency_context": dependency_text(dependencies),
        "citations": list(evidence.values()), "allow_web": task.allow_web,
        "dependency_cards": [card for dep in dependencies.values() for card in dep.get("article_cards", [])],
        "execution_mode": "delegate" if task.actor == "subagent" else "direct",
        "capabilities": sorted(task_capabilities(task)),
        "cancelled": False, "reflection_feedback": "", "worker_results": [],
    }


def dependency_text(dependencies):
    text = json.dumps(dependencies, ensure_ascii=False)
    if len(text) > settings.DEPENDENCY_MAX_CHARS or count_tokens(text) > input_budget(settings.WORKER_OUTPUT_MAX_TOKENS):
        raise ContextBudgetExceeded("依赖资料超出当前任务上下文预算，请收窄任务")
    return text


REFERENCE = re.compile(r"\[((?:[a-z][a-z0-9_]*:)?(?:web)?\d+)\](?!\()")


def invalid_references(text, citations):
    text = re.sub(r"```.*?```|`[^`]*`", "", text, flags=re.DOTALL)
    allowed = {str(c["id"]) for c in citations}
    return set(REFERENCE.findall(text)) - allowed


def used_evidence(text, citations, cards):
    """Allowed evidence is not automatically a source used in the answer."""
    visible_text = re.sub(r"```.*?```|`[^`]*`", "", text, flags=re.DOTALL)
    referenced = set(REFERENCE.findall(visible_text))
    selected = [c for c in citations if str(c["id"]) in referenced]
    article_ids = {str(c.get("articleId")) for c in selected if c.get("articleId")}
    return selected, [card for card in cards if str(card["articleId"]) in article_ids]


def task_result(state, update, *, raw_retrieval=False):
    actor = "subagent" if state.get("execution_mode") == "delegate" else "main"
    task = load_execution_task(state["current_task"], actor)
    if raw_retrieval and not (task.kind == "search" and task.actor == "main" and task.retrieval_target == "knowledge"):
        raise PermissionError("只有主代理的原始知识检索可以标记资料正文")
    workers = update.get("worker_results") or []
    if len(workers) != 1 or not (workers[0].get("result") or "").strip():
        raise ValueError("执行任务没有唯一有效结果")
    citations = update.get("citations", state.get("citations", []))
    cards = update.get("article_cards", state.get("dependency_cards", []))
    memory_lookup = task.retrieval_target == "memory"
    if memory_lookup and (citations or cards):
        raise ValueError("记忆结果不能携带文章引用或卡片")
    result = workers[0]
    # Search returns source data rather than generated prose; it uses the input
    # allowance. Generated analysis/writing use the worker output allowance.
    result_tokens = input_budget(settings.WORKER_OUTPUT_MAX_TOKENS) if task.kind == "search" else settings.WORKER_OUTPUT_MAX_TOKENS
    if len(result["result"]) > settings.TASK_RESULT_MAX_CHARS or count_tokens(result["result"]) > result_tokens:
        raise ValueError("执行任务输出超出预算")
    status = result.get("status", "succeeded")
    if status in ("success", "degraded"):
        status = "succeeded"
    # Stored historical text may contain old reference markers; it is data,
    # not a freshly generated answer with public article evidence.
    # Original documents can quote footnotes and old chat references. They are
    # data, not newly authored citations; generated outputs still use this gate.
    if status == "succeeded" and not memory_lookup and not raw_retrieval and invalid_references(result["result"], citations):
        status = "invalid_citation"
    if status == "succeeded" and task.requires_evidence and not citations:
        status = "insufficient_evidence"
    return {"task_id": task.task_id, "kind": task.kind, "actor": task.actor, "status": status,
            "retrieval_target": task.retrieval_target, "result": result["result"], "citations": citations,
            "article_cards": cards,
            **({"retrieval_report": update["retrieval_report"]} if update.get("retrieval_report") else {}),
            **({'citation_contents': {str(c['id']): update['citation_contents'][str(c['id'])]
                                     for c in citations if str(c['id']) in update['citation_contents']}}
               if raw_retrieval and update.get('citation_contents') else {}),
            **({"memory_sources": update.get("memory_sources", []), "memory_found": update["memory_found"],
                "memory_match_count": update["memory_match_count"]} if memory_lookup else {}),
            "draft_article_id": update.get("draft_article_id"),
            "draft_title": result.get("draft_title", ""),
            "instruction": task.instruction}


async def assert_run(state):
    if state.get("run_id"):
        await run_repository.assert_executor(state["run_id"], executor_token(state))


def executor_token(state):
    # Resume uses the existing checkpoint and a newly claimed executor token.
    # Run configuration is issued by RunService, never model-generated state.
    try:
        return get_config()["configurable"].get("execution_token", state["execution_token"])
    except RuntimeError:
        return state["execution_token"]


def guard_node(name, function):
    async def guarded(state):
        await assert_run(state)
        run_id = state.get("run_id")
        started = time.perf_counter()
        round_number = state.get("main_round", 0) + (name == "main_agent")
        label = f"{state['task_id']}.{name}" if state.get("task_id") else f"round_{round_number}.{name}"
        if run_id:
            await run_repository.event(run_id, label, "started")
            if hasattr(run_repository, 'mark_recovery_node'):
                await run_repository.mark_recovery_node(run_id, executor_token(state), name)
        await node_activity(state, name, "active")
        try:
            output = function(state)
            if inspect.isawaitable(output):
                output = await output
            from app.services.run_metrics import metrics_from
            metrics = metrics_from(get_config())
            if run_id and metrics and hasattr(run_repository, 'persist_metrics'):
                await run_repository.persist_metrics(run_id, executor_token(state), metrics)
            if run_id:
                await run_repository.event(run_id, label, "succeeded", int((time.perf_counter()-started)*1000))
            await node_activity(state, name, "done")
            return output
        except GraphInterrupt:
            if run_id:
                await run_repository.event(run_id, label, "interrupted", int((time.perf_counter()-started)*1000))
            await node_activity(state, name, "paused")
            raise
        except BaseException:
            from app.services.run_metrics import metrics_from
            metrics = metrics_from(get_config())
            if run_id and metrics and hasattr(run_repository, 'persist_metrics'):
                await run_repository.persist_metrics(run_id, executor_token(state), metrics)
            if run_id:
                await run_repository.event(run_id, label, "failed", int((time.perf_counter()-started)*1000))
            await node_activity(state, name, "error")
            raise
    return guarded


async def subagent_node(state):
    await assert_run(state)
    started = time.perf_counter()
    task = load_execution_task(state["current_task"], "subagent")
    if state.get("execution_mode") != "delegate" or task.kind not in ("search", "analysis"):
        raise PermissionError("子代理执行入口仅接受受控只读委派任务")
    runners = {"search": search_worker_node, "analysis": analysis_worker_node}
    if state.get("run_id"):
        await run_repository.event(state["run_id"], task.task_id, "started")
    await activity(state, "task", {"search": "检索资料", "analysis": "分析资料"}[task.kind])
    try:
        update = await asyncio.wait_for(runners[task.kind](state), 120)
        result = task_result(state, update)
        # A citation formatting fault does not justify another retrieval call.
        if result["status"] == "invalid_citation" and task.kind != "search":
            await activity(state, "citation_correction", "修正引用格式")
            retry_state = {**state, "reflection_feedback": "只使用已提供的引用编号，删除无法匹配证据的引用。"}
            update = await asyncio.wait_for(runners[task.kind](retry_state), 60)
            result = task_result(state, update)
            await activity(state, "citation_correction", "修正引用格式",
                           "done" if result["status"] == "succeeded" else "error")
        await assert_run(state)
        if state.get("run_id"):
            await run_repository.event(state["run_id"], task.task_id, result["status"], int((time.perf_counter()-started)*1000))
        await activity(state, "task", {"search": "检索资料", "analysis": "分析资料"}[task.kind],
                       "done" if result["status"] == "succeeded" else "error")
        return {"task_results": {task.task_id: result}}
    except BaseException:
        if state.get("run_id"):
            await run_repository.event(state["run_id"], task.task_id, "failed", int((time.perf_counter()-started)*1000))
        await activity(state, "task", "执行子任务", "error")
        raise


async def final_gate(state):
    await assert_run(state)
    text = state.get("final_reply", "")
    if not text.strip():
        raise ValueError("汇总没有有效回复")
    if invalid_references(text, state.get("citations", [])):
        raise ValueError("最终回复包含不存在的引用")
    await verify_public_evidence(state.get("citations", []))
    return {}
