"""Shared Phase 0 input and result contracts for chat and resume protocols."""
import logging
import json

from fastapi import HTTPException

from app.graph.state_factory import create_initial_state
from app.services.image_understanding import preprocess_message
from app.services.run_repository import run_repository, digest
from app.services.durable_jobs import durable_jobs
from app.services.article_context import article_context_service
from app.services.run_metrics import RunMetrics, metrics_from
from app.services.executor_heartbeat import maintain_executor
from app.services.run_history import run_history

log = logging.getLogger(__name__)


def interrupt_payload(snapshot):
    if snapshot.next:
        for task in snapshot.tasks:
            if task.interrupts:
                return task.interrupts[0].value
    return None


def unique_items(items: list[dict], key: str) -> list[dict]:
    seen = set()
    result = []
    for item in items or []:
        value = str(item.get(key) or "")
        if value and value not in seen:
            seen.add(value)
            result.append(item)
    return result


def public_run_result(raw):
    """Recovery artifacts/input anchors stay server-side, outside response payloads."""
    if raw is None:
        return None
    result = json.loads(raw) if isinstance(raw, str) else raw
    return {key: value for key, value in result.items() if key not in ('progress', 'user_message_id', 'draft_commit')}


class RunService:
    def __init__(self, conversations, memory, repository=run_repository, jobs=durable_jobs, articles=article_context_service, history=run_history):
        self.conversations = conversations
        self.memory = memory
        self.jobs = jobs
        self.repository = repository
        self.articles = articles
        self.history = history

    async def prepare_chat(self, request, graph, admission_ticket=None):
        for image in request.image_paths or []:
            normalized = image.replace("\\", "/")
            if not normalized.startswith(f"ai-chat/{request.user_id}/") or ".." in normalized.split("/"):
                raise HTTPException(403, "图片不属于当前用户的上传目录")
        is_new = request.conversation_id is None
        conv_id = request.conversation_id
        request_id = str(request.request_id)
        origin = request.origin_article_id
        if not is_new:
            origin = await self.conversations.resolve_origin(conv_id, request.user_id, origin)
        # Validate current visibility before creating a conversation or appending
        # user messages. This read is repeated on every new execution, not cached
        # in history or trusted from a browser-supplied article body.
        article = None
        if origin is not None:
            try:
                article = await self.articles.load(origin)
            except HTTPException as exc:
                # An unavailable source stops creation from that article. An
                # existing conversation can continue on other topics, without
                # treating an old historical snapshot as current article data.
                if is_new or exc.status_code != 404:
                    raise
        inputs = {"message": request.message, "images": request.image_paths or []}
        if origin is not None:
            inputs["origin_article_id"] = origin
        input_hash = digest(inputs)
        previous = await self.repository.find_request(request.user_id, request_id)
        if previous:
            if previous["input_hash"] != input_hash or (conv_id is not None and conv_id != previous["conversation_id"]):
                raise HTTPException(409, "幂等请求与原始输入不一致")
            await self.conversations.resolve_origin(previous["conversation_id"], request.user_id, origin)
            previous = await self.reconcile_saved(previous)
            if previous["status"] not in ("succeeded", "awaiting_approval"):
                raise HTTPException(409, "请求正在执行或已失败，请查询运行状态")
            return previous["conversation_id"], self.config(previous, replay=True), None
        if is_new:
            conv_id = await self.conversations.create_conversation(request.user_id, origin_article_id=origin)
        run, created = await self.repository.create(conv_id, request.user_id, request_id, input_hash)
        if not created:
            raise HTTPException(409, "请求已经存在")
        config = self.config(run, repository=self.repository)
        try:
            if admission_ticket:
                await self.repository.bind_admission(run['run_id'], run['execution_token'], admission_ticket)
                config['configurable']['admission_ticket'] = run['execution_token']
            async with maintain_executor(self.repository, config):
                context = await self.conversations.get_context_for_llm(conv_id)
                message_id = await self.conversations.add_message(conv_id, "user", request.message, image_paths=request.image_paths)
                if message_id:
                    config['configurable']['user_message_id'] = str(message_id)
                if message_id and hasattr(self.repository, 'record_input'):
                    await self.repository.record_input(run['run_id'], run['execution_token'], message_id)
                message = await preprocess_message(request.message, request.image_paths)
                # No embedding or recall model on this path.
                memory_context = await self.memory.load_context(request.user_id, conv_id)
                previous_run, reusable = ({}, {})
                if not is_new:
                    previous_run, reusable = await self.history.previous(conv_id, request.user_id, run['run_id'])
        except BaseException:
            await self.repository.fail(run["run_id"], run["execution_token"])
            raise
        state = create_initial_state(request.user_id, message, context)
        state.update(run_id=run["run_id"], execution_token=run["execution_token"],
                     conversation_id=conv_id, memory_source_message=request.message, **memory_context)
        state["origin_article_id"] = origin
        state['previous_run'] = {**previous_run, 'reusable_results': reusable} if previous_run else {}
        if origin is not None and article is None:
            state["article_context"] = {"article_id": str(origin), "availability": "unavailable",
                "notice": "来源文章已不可读；历史中的旧正文不代表当前版本。可以继续讨论其他主题或检索其他文章。"}
        if article is not None:
            state["article_context"] = {key: value for key, value in article.items()
                                        if key not in ("content", "citation")}
            source = {**self.articles.evidence(article), "source_context": True}
            state["task_results"] = {source["task_id"]: source}
        return conv_id, config, state

    @staticmethod
    def config(run, replay=False, repository=None):
        previous = json.loads(run.get('result_json') or '{}').get('metrics')
        persist = (lambda metrics: repository.persist_metrics(run['run_id'], run['execution_token'], metrics)) \
                  if repository and hasattr(repository, 'persist_metrics') else None
        return {"configurable": {"thread_id": f"run_{run['run_id']}", "run_id": run["run_id"],
                                 "execution_token": run["execution_token"], "replay": replay},
                "callbacks": [] if replay else [RunMetrics(previous, persist=persist)],
                "recursion_limit": 80}

    @staticmethod
    def recovery_candidate(run):
        result = run.get('result_json') or '{}'
        result = json.loads(result) if isinstance(result, str) else result
        return (run['status'] in ('failed', 'expired') and not run.get('draft_article_id')
                and not run.get('recovery_count', 0) and result.get('recovery_node') == 'main_delegate')

    async def recovery_snapshot(self, run, graph):
        if not self.recovery_candidate(run):
            return None
        snapshot = await graph.aget_state(self.config(run))
        if (tuple(snapshot.next) != ('main_delegate',) or snapshot.values.get('cancelled')
                or snapshot.values.get('business_complete') or interrupt_payload(snapshot)):
            return None
        from app.graph.staged_plan import load_execution_plan
        try:
            plan = load_execution_plan(snapshot.values['plan'], 'subagent')
        except (KeyError, ValueError):
            return None
        if any(task.kind not in ('search', 'analysis') for task in plan.tasks):
            return None
        return snapshot

    async def prepare_recovery(self, rid, uid, graph, ticket):
        run = await self.repository.get(rid)
        if not run or run['user_id'] != uid:
            raise HTTPException(404, '运行不存在')
        await self.conversations.require_owner(run['conversation_id'], uid)
        if await self.recovery_snapshot(run, graph) is None:
            raise HTTPException(409, '只支持恢复未完成的只读委派任务')
        run = await self.repository.claim_recovery(run['conversation_id'], uid, rid)
        try:
            await self.repository.bind_admission(rid, run['execution_token'], ticket)
        except BaseException:
            await self.repository.fail(rid, run['execution_token'])
            raise
        config = self.config(run, repository=self.repository)
        config['configurable']['admission_ticket'] = run['execution_token']
        return run['conversation_id'], config

    async def approval_conflict(self, rid, detail):
        try:
            await self.repository.event(rid, 'approval', 'conflict')
        except Exception as exc:
            log.warning('审批冲突监控写入失败: %s', type(exc).__name__)
        return HTTPException(409, detail)

    async def prepare_resume(self, request, graph, admission_ticket=None):
        await self.conversations.require_owner(request.conversation_id, request.user_id)
        current = await self.repository.get(str(request.run_id))
        if not current or current["conversation_id"] != request.conversation_id or current["user_id"] != request.user_id:
            raise HTTPException(409, "审批运行不存在")
        config = self.config(current)
        snapshot = await graph.aget_state(config)
        if snapshot.values.get("cancelled") or interrupt_payload(snapshot) is None:
            raise await self.approval_conflict(str(request.run_id), "当前会话没有可恢复的审批")
        if interrupt_payload(snapshot).get("draftHash") != request.draft_hash:
            raise await self.approval_conflict(str(request.run_id), "审批内容与检查点版本不一致")
        edited = getattr(request, 'edited_draft', None)
        if edited is not None:
            if request.action == 'reject':
                raise HTTPException(422, "放弃保存时不能提交编辑内容")
            # Validate before claiming the run, so invalid edits leave approval usable.
            from app.graph.staged_runtime import invalid_references
            payload = interrupt_payload(snapshot)
            allowed = payload.get('citations', [])
            old_markers = invalid_references(payload.get('draft', ''), allowed)
            if invalid_references(edited.content, allowed) - old_markers:
                raise HTTPException(422, "编辑内容包含未知引用编号，请保留已有引用或移除无效引用")
        try:
            run = await self.repository.claim_resume(request.conversation_id, request.user_id,
                                                   str(request.run_id), request.draft_hash)
        except HTTPException as exc:
            if exc.status_code == 409:
                await self.approval_conflict(str(request.run_id), str(exc.detail))
            raise
        config = self.config(run, repository=self.repository)
        if admission_ticket:
            try:
                await self.repository.bind_admission(run['run_id'], run['execution_token'], admission_ticket)
                config['configurable']['admission_ticket'] = run['execution_token']
            except BaseException:
                await self.repository.fail(run['run_id'], run['execution_token'])
                raise
        # Inputs do not re-enter the planner. The runtime config carries the
        # new fencing token; generated content remains in its original checkpoint.
        return request.conversation_id, config

    async def finish(self, conv_id: int, user_id: int, snapshot, config=None) -> dict:
        values = snapshot.values
        result = {
            "reply": values.get("final_reply") or "",
            "articles": unique_items(values.get("article_cards"), "articleId"),
            "citations": unique_items(values.get("citations"), "id"),
            "draft_article_id": values.get("draft_article_id"),
            "interrupted": interrupt_payload(snapshot),
            "cancelled": bool(values.get("cancelled")),
        }
        if metrics := metrics_from(config):
            result['metrics'] = metrics
        if result["interrupted"] is not None or result["cancelled"]:
            if config and result["interrupted"] is not None:
                cfg = config["configurable"]
                await self.repository.settle(conv_id, user_id, cfg["run_id"], cfg["execution_token"],
                                             "awaiting_approval", result)
            return result
        if snapshot.next or not result["reply"].strip():
            raise RuntimeError("运行未完成或未产生有效回复")
        if audit := values.get('grounding_audit'):
            result['grounding_audit'] = audit
            from app.graph.staged_runtime import used_evidence
            evidence = values.get('delivery_evidence') or {}
            result['citations'], result['articles'] = used_evidence(result['reply'],
                unique_items(evidence.get('citations', result['citations']), 'id'),
                unique_items(evidence.get('article_cards', result['articles']), 'articleId'))
        async def append_message():
            await self.conversations.add_message(
                conv_id, "assistant", result["reply"], article_cards=result["articles"] or None,
                citations=result["citations"] or None, draft_article_id=result["draft_article_id"], postprocess=False)
        if config:
            cfg = config["configurable"]
            result = await self.repository.settle(conv_id, user_id, cfg["run_id"], cfg["execution_token"],
                                                  "succeeded", result, append_message)
            await self.conversations.invalidate_cache(conv_id)
        else:
            await append_message()
        return public_run_result(result)

    async def cached_result(self, config):
        run = await self.repository.get(config["configurable"]["run_id"])
        return public_run_result(run["result_json"])

    async def reconcile_saved(self, run):
        if run["status"] == "running" and run["draft_article_id"]:
            recovered = {"reply": "草稿已保存到草稿箱，可继续编辑。", "articles": [], "citations": [],
                         "draft_article_id": run["draft_article_id"], "interrupted": None, "cancelled": False}
            async def append_recovered():
                await self.conversations.add_message(run["conversation_id"], "assistant", recovered["reply"],
                                                    draft_article_id=run["draft_article_id"], postprocess=False)
            await self.repository.settle(run["conversation_id"], run["user_id"], run["run_id"],
                                          run["execution_token"], "succeeded", recovered, append_recovered)
            await self.conversations.invalidate_cache(run["conversation_id"])
            run = await self.repository.get(run["run_id"])
        return run

    async def shutdown(self):
        pass  # Durable worker lifetime belongs to the FastAPI lifespan.
