"""FastAPI adapters sharing chat/resume state and persistence contracts."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, UTC

import asyncio
import sys
from uuid import UUID, uuid4
from fastapi import FastAPI, Depends, HTTPException, Query, Path
from typing import Literal
from langgraph.types import Command
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse
from starlette.responses import JSONResponse
from app.services.operations import operations

from app.clients import mysql_client
from app.clients.mcp_client import mcp_manager
from app.config import settings
from app.graph.builder import get_graph, close_graph
from app.migrate import check_message_schema, check_content_schema, check_jobs_schema, check_article_conversation_schema, check_delivery_schema
from app.services.durable_jobs import background_worker
from app.services.conversation import ConversationService
from app.services.logging_config import setup_logging, get_logger, set_request_trace, set_run_trace
from app.services.memory import memory_service
from app.services.run_service import RunService
from app.services.executor_heartbeat import maintain_executor
from app.services.execution_admission import execution_admission
from app.services.stream_delivery import stream_delivery
from app.services.answer_stream import DirectAnswerStream
from app.services.tool_registry import tool_registry
from app.security.principal import Principal, require_principal, match_user
from app.services.run_repository import run_repository
from app.models.draft import EditedDraft
from app.services.memory_management import memory_management, ProfileEdit, RecordEdit
from app.migrate import check_runtime_schema, check_memory_schema
from app.migrate import check_optimization_schema, check_heartbeat_schema, check_maintenance_schema
from app.migrate import check_task_recovery_schema

setup_logging(level="INFO")
log = get_logger(__name__)
conversation_service = ConversationService()
run_service = RunService(conversation_service, memory_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rpc_server = None
    log.info("Agent Token budgets: total=%d main_output=%d worker_output=%d safety=%d compact_trigger=%d compact_target=%d recent=%d summary=%d",
             settings.MAIN_CONTEXT_MAX_TOKENS, settings.MAIN_OUTPUT_MAX_TOKENS, settings.WORKER_OUTPUT_MAX_TOKENS,
             settings.CONTEXT_SAFETY_TOKENS, settings.CONTEXT_COMPACT_TRIGGER_TOKENS, settings.CONTEXT_COMPACT_TARGET_TOKENS, settings.HISTORY_RECENT_TOKENS,
             settings.SUMMARY_MAX_TOKENS)
    await mysql_client.startup()
    try:
        await check_message_schema(mysql_client.db)
        await check_content_schema(mysql_client.db)
        await check_runtime_schema(mysql_client.db)
        await check_memory_schema(mysql_client.db)
        await check_jobs_schema(mysql_client.db)
        await check_article_conversation_schema(mysql_client.db)
        await check_delivery_schema(mysql_client.db)
        await check_heartbeat_schema(mysql_client.db)
        await check_maintenance_schema(mysql_client.db)
        await check_task_recovery_schema(mysql_client.db)
        from app.migrate import check_service_boundaries
        await check_service_boundaries(mysql_client.db)
        from app.migrate import check_product_features
        await check_product_features(mysql_client.db)
        if len(settings.AGENT_SERVICE_KEY.encode()) < 32:
            raise RuntimeError("请为 Java 和 Python 配置相同的 AGENT_SERVICE_KEY，至少32字节")
        from app.clients.es_client import BaseEsClient
        es = BaseEsClient()
        try:
            await es.ensure_user_memories_index()
        finally:
            await es.client.close()
        # Fail startup if RedisJSON/RediSearch or checkpoint indexes are unavailable.
        # Otherwise /health can succeed while the first chat/approval fails.
        await get_graph()
        server_configs = json.loads(settings.MCP_SERVERS_JSON)
        if server_configs:
            await mcp_manager.connect(server_configs)
            tool_registry.refresh()
        background_worker.start()
        if settings.INTERNAL_TRANSPORT not in ('http', 'triple'):
            raise RuntimeError('AGENT_INTERNAL_TRANSPORT 必须是 http 或 triple')
        if settings.AGENT_RPC_ENABLED:
            from app.rpc.server import start_server
            rpc_server = await start_server(sys.modules[__name__])
        from app.rpc.discovery import catalog
        if catalog.enabled and (not settings.AGENT_RPC_ENABLED or settings.INTERNAL_TRANSPORT != 'triple'):
            raise RuntimeError('服务发现模式需要启用 Triple RPC')
        await catalog.start()
        yield
    finally:
        if rpc_server is not None:
            await rpc_server.stop(3)
        await stream_delivery.shutdown()
        await background_worker.shutdown()
        await run_service.shutdown()
        await close_graph()
        await mcp_manager.shutdown()
        await mysql_client.shutdown()
        from app.rpc.blog_client import close_client
        from app.rpc.discovery import catalog
        await catalog.close()
        await close_client()
        from app.services.main_context import context_service
        await context_service._redis.client.aclose()


app = FastAPI(title="EasyJob Python Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    user_id: int = Field(gt=0)
    conversation_id: int | None = Field(default=None, gt=0)
    origin_article_id: int | None = Field(default=None, gt=0)
    message: str = Field(min_length=1, max_length=16000)
    image_paths: list[str] | None = Field(default=None, max_length=4)
    request_id: UUID = Field(default_factory=uuid4)


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ChatResponse(BaseModel):
    model_config = {"alias_generator": _to_camel, "populate_by_name": True}
    reply: str
    conversation_id: str
    articles: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    draft_article_id: str | None = None
    run_id: str


class ResumeRequest(BaseModel):
    user_id: int = Field(gt=0)
    conversation_id: int = Field(gt=0)
    action: str = Field(min_length=1, max_length=4000)
    run_id: UUID
    draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    edited_draft: EditedDraft | None = None


NODE_TO_PROGRESS = {
    "main_agent": "planner", "main_retrieve": "search",
    "main_delegate": "subagent", "prepare_draft": "writing", "collect_draft": "writing",
    "planner": "planner", "search_worker": "search", "chat_worker": "chat",
    "analysis_worker": "analysis", "writing_worker": "writing", "synthesizer": "synthesizer",
}


def _sse(data: str) -> str:
    return f"data:{data.replace(chr(10), '\\n')}\n\n"


def _answer_frames(text):
    """Chunk a committed, verified answer without artificial typing delays."""
    yield _sse('__ANSWER__:' + json.dumps({"type": "start"}))
    chunks = [text[i:i + 512] for i in range(0, len(text), 512)]
    for seq, content in enumerate(chunks):
        yield _sse('__ANSWER__:' + json.dumps({"type": "delta", "seq": seq, "content": content}, ensure_ascii=False))
    yield _sse('__ANSWER__:' + json.dumps({"type": "end", "chunks": len(chunks)}))
    # Canonical replacement also supports older clients and replay recovery.
    yield _sse('__REPLY__:' + json.dumps({"content": text}, ensure_ascii=False))


async def _complete(graph, conv_id, user_id, config) -> dict:
    if config["configurable"].get("replay"):
        return await run_service.cached_result(config)
    snapshot = await graph.aget_state(config)
    return await run_service.finish(conv_id, user_id, snapshot, config)


async def _invoke(graph, graph_input, conv_id, user_id, config) -> ChatResponse:
    set_request_trace(conv_id)
    set_run_trace(config['configurable']['run_id'])
    recovered = None
    if not config["configurable"].get("replay"):
        try:
            async with asyncio.timeout(settings.RUN_TIMEOUT_SECONDS):
                await graph.ainvoke(graph_input, config=config)
        except BaseException:
            await run_service.repository.fail(config["configurable"]["run_id"], config["configurable"]["execution_token"])
            run = await run_service.repository.get(config["configurable"]["run_id"])
            if not run or not run.get("draft_article_id"):
                raise
            run = await run_service.reconcile_saved(run)
            recovered = json.loads(run["result_json"])
    try:
        result = recovered or await _complete(graph, conv_id, user_id, config)
    except BaseException:
        await run_service.repository.fail(config["configurable"]["run_id"], config["configurable"]["execution_token"])
        raise
    if result["interrupted"] is not None:
        reply = json.dumps({"interrupted": True, "payload": result["interrupted"]}, ensure_ascii=False)
    elif result["cancelled"]:
        reply = "请求已取消。"
    else:
        reply = result["reply"]
    return ChatResponse(reply=reply, conversation_id=str(conv_id), articles=result["articles"],
                        citations=result["citations"],
                        run_id=config["configurable"]["run_id"],
                        draft_article_id=str(result["draft_article_id"]) if result["draft_article_id"] else None)


def _stream_source(graph, graph_input, conv_id, user_id, config):
    async def generate():
        set_request_trace(conv_id)
        set_run_trace(config['configurable']['run_id'])
        yield _sse(f"__CONV_ID__:{conv_id}")
        yield _sse(f"__RUN_ID__:{config['configurable']['run_id']}")
        if config['configurable'].get('user_message_id'):
            yield _sse(f"__INPUT_ID__:{config['configurable']['user_message_id']}")
        started_nodes = set()
        answer_stream = DirectAnswerStream(min_interval=settings.STREAM_COALESCE_MS / 1000)
        try:
            async def events():
                if not config["configurable"].get("replay"):
                    async with asyncio.timeout(settings.RUN_TIMEOUT_SECONDS):
                        async for item in graph.astream_events(graph_input, config=config, version="v2"):
                            yield item
            async for event in events():
                payloads = answer_stream.consume(event)
                if payloads:
                    await run_service.repository.assert_executor(config['configurable']['run_id'],
                                                                 config['configurable']['execution_token'])
                for payload in payloads:
                    yield _sse('__ANSWER__:' + json.dumps(payload, ensure_ascii=False))
                kind = event["event"]
                node = event.get("metadata", {}).get("langgraph_node")
                if kind == "on_custom_event" and event.get("name") == "agent_event":
                    yield _sse("__AGENT_EVENT__:" + json.dumps(event["data"], ensure_ascii=False))
                if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                    started_nodes.add(node)
                    if NODE_TO_PROGRESS[node] in ("planner", "synthesizer"):
                        yield _sse(f"__PROGRESS__:{NODE_TO_PROGRESS[node]}")
                    elif "dispatcher" not in started_nodes:
                        started_nodes.add("dispatcher")
                        snapshot = await graph.aget_state(config)
                        workers = snapshot.values.get("active_workers") or [NODE_TO_PROGRESS[node]]
                        yield _sse(f"__PROGRESS__:dispatcher:{','.join(workers)}")
                # Only an explicitly eligible source-free Main answer streams.
                # Retrieved answers, repairs and drafts stay private until gated.
            result = await _complete(graph, conv_id, user_id, config)
            if result["interrupted"] is not None:
                yield _sse('__AGENT_EVENT__:' + json.dumps({"version": 1, "kind": "status", "status": "awaiting"}))
                yield _sse("__INTERRUPTED__:" + json.dumps(result["interrupted"], ensure_ascii=False))
            elif result["cancelled"]:
                yield _sse('__AGENT_EVENT__:' + json.dumps({"version": 1, "kind": "status", "status": "cancelled"}))
                yield _sse("[ERROR] 请求已取消")
            else:
                if result["articles"]:
                    yield _sse("__ARTICLES__:" + json.dumps(result["articles"], ensure_ascii=False))
                if result["citations"]:
                    yield _sse("__CITATIONS__:" + json.dumps(result["citations"], ensure_ascii=False))
                if answer_stream.started:
                    for payload in answer_stream.finish(result['reply']):
                        yield _sse('__ANSWER__:' + json.dumps(payload, ensure_ascii=False))
                    yield _sse('__REPLY__:' + json.dumps({'content': result['reply']}, ensure_ascii=False))
                else:
                    for frame in _answer_frames(result["reply"]):
                        yield frame
                if result["draft_article_id"]:
                    snapshot = await graph.aget_state(config)
                    title = next((r.get("draft_title", "") for r in snapshot.values.get("worker_results", [])
                                  if r.get("draft_article_id") == result["draft_article_id"]), "")
                    yield _sse("__DRAFT_SAVED__:" + json.dumps({
                        "draftArticleId": str(result["draft_article_id"]), "title": title,
                    }, ensure_ascii=False))
                incomplete = result.get('delivery_status') == 'incomplete'
                yield _sse('__AGENT_EVENT__:' + json.dumps({"version": 1, "kind": "status", "status": "error" if incomplete else "complete"}))
                if not incomplete:
                    yield _sse("__PROGRESS__:done")
        except Exception as error:
            await run_service.repository.fail(config["configurable"]["run_id"], config["configurable"]["execution_token"])
            log.exception("Agent 运行失败: conv=%s", conv_id)
            run = await run_service.repository.get(config["configurable"]["run_id"])
            if run and run.get("draft_article_id"):
                run = await run_service.reconcile_saved(run)
                for frame in _answer_frames("草稿已保存到草稿箱，可继续编辑。"):
                    yield frame
                yield _sse("__DRAFT_SAVED__:" + json.dumps({"draftArticleId": str(run["draft_article_id"]), "title": ""}))
                yield _sse('__AGENT_EVENT__:' + json.dumps({"version": 1, "kind": "status", "status": "complete"}))
                yield _sse("__PROGRESS__:done")
            else:
                yield _sse('__AGENT_EVENT__:' + json.dumps({"version": 1, "kind": "status", "status": "error"}))
                from app.services.run_metrics import RunTokenBudgetExceeded
                from app.services.draft_gateway import DraftConflict
                from app.services.grounding import DraftVerificationError
                message = str(error) if isinstance(error, (RunTokenBudgetExceeded, DraftConflict, DraftVerificationError)) else (
                    "本次处理超时，已结束运行，可以重新发送请求。" if isinstance(error, TimeoutError)
                    else "Agent 处理失败，请稍后重试")
                yield _sse("[ERROR] " + message)
        finally:
            # This producer belongs to the application, not to an HTTP connection.
            await run_service.repository.fail(config["configurable"]["run_id"], config["configurable"]["execution_token"])
        yield _sse(json.dumps({"conversationId": str(conv_id)}))
        yield _sse("[DONE]")
    return generate()


async def _prepare_chat(request, graph):
    ticket = await execution_admission.acquire(request.user_id)
    try:
        cid, config, state = await run_service.prepare_chat(request, graph, admission_ticket=ticket)
        config['configurable'].setdefault('admission_ticket', ticket)
        return cid, config, state
    except BaseException:
        await asyncio.shield(execution_admission.release(ticket))
        raise


async def _prepare_resume(request, graph):
    ticket = await execution_admission.acquire(request.user_id)
    try:
        cid, config = await run_service.prepare_resume(request, graph, admission_ticket=ticket)
        config['configurable'].setdefault('admission_ticket', ticket)
        return cid, config
    except BaseException:
        await asyncio.shield(execution_admission.release(ticket))
        raise


async def _invoke_admitted(graph, graph_input, cid, uid, config):
    try:
        async with maintain_executor(run_repository, config):
            return await _invoke(graph, graph_input, cid, uid, config)
    finally:
        await asyncio.shield(execution_admission.release(config['configurable'].get('admission_ticket')))


def _stream(graph, graph_input, cid, uid, config):
    cfg = config['configurable']
    stream_delivery.start(cfg['run_id'], cfg['execution_token'],
        _stream_source(graph, graph_input, cid, uid, config), cfg.get('admission_ticket'),
        replay=cfg.get('replay', False))
    return StreamingResponse(stream_delivery.follow(cfg['run_id'], cfg['execution_token']),
        media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/runs/{run_id}/events')
async def replay_events(run_id: UUID, after: int = Query(default=0, ge=0), principal: Principal = Depends(require_principal)):
    run = await run_repository.get(str(run_id))
    if not run or run['user_id'] != principal.user_id: raise HTTPException(404, '运行不存在')
    await conversation_service.require_owner(run['conversation_id'], principal.user_id)
    return StreamingResponse(stream_delivery.follow(str(run_id), run['execution_token'], after),
        media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/runs/{run_id}/recover')
async def recover_run(run_id: UUID, principal: Principal = Depends(require_principal)):
    graph = await get_graph()
    ticket = await execution_admission.acquire(principal.user_id)
    try:
        cid, config = await run_service.prepare_recovery(str(run_id), principal.user_id, graph, ticket)
        return _stream(graph, None, cid, principal.user_id, config)
    except BaseException:
        await asyncio.shield(execution_admission.release(ticket))
        raise


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get('/health/ready')
async def readiness():
    result = await operations.readiness()
    return JSONResponse(result, status_code=200 if result['status'] == 'ready' else 503)


@app.get('/internal/metrics')
async def operational_metrics(principal: Principal = Depends(require_principal)):
    return await operations.metrics()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, principal: Principal = Depends(require_principal)):
    match_user(principal, request.user_id)
    graph = await get_graph()
    conv_id, config, state = await _prepare_chat(request, graph)
    return await _invoke_admitted(graph, state, conv_id, request.user_id, config)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, principal: Principal = Depends(require_principal)):
    match_user(principal, request.user_id)
    graph = await get_graph()
    conv_id, config, state = await _prepare_chat(request, graph)
    return _stream(graph, state, conv_id, request.user_id, config)


@app.post("/chat/resume", response_model=ChatResponse)
async def chat_resume(request: ResumeRequest, principal: Principal = Depends(require_principal)):
    match_user(principal, request.user_id)
    graph = await get_graph()
    conv_id, config = await _prepare_resume(request, graph)
    return await _invoke_admitted(graph, Command(resume={"action": request.action, "runId": str(request.run_id),
                                               "draftHash": request.draft_hash,
                                               "editedDraft": request.edited_draft.model_dump() if request.edited_draft else None}), conv_id, request.user_id, config)


@app.post("/chat/resume/stream")
async def chat_resume_stream(request: ResumeRequest, principal: Principal = Depends(require_principal)):
    match_user(principal, request.user_id)
    graph = await get_graph()
    conv_id, config = await _prepare_resume(request, graph)
    return _stream(graph, Command(resume={"action": request.action, "runId": str(request.run_id),
                                        "draftHash": request.draft_hash,
                                        "editedDraft": request.edited_draft.model_dump() if request.edited_draft else None}), conv_id, request.user_id, config)


@app.post("/chat/{conversation_id}/cancel")
async def cancel_chat(conversation_id: int, user_id: int, principal: Principal = Depends(require_principal)):
    match_user(principal, user_id)
    await conversation_service.require_owner(conversation_id, user_id)
    result = await run_repository.cancel(conversation_id, user_id)
    if result.get('status') == 'cancelled' and result.get('runId'):
        from app.services.executor_heartbeat import cancel_local_run
        cancel_local_run(result['runId'])
    return result


@app.get("/conversations")
async def list_conversations(user_id: int, last_update_time: datetime | None = None,
                             last_id: int | None = None, limit: int = 10,
                             scope: Literal["all", "general", "article"] = "all",
                             origin_article_id: int | None = Query(default=None, gt=0),
                             principal: Principal = Depends(require_principal)):
    match_user(principal, user_id)
    if not 1 <= limit <= 100:
        raise HTTPException(422, "分页范围无效")
    return {"data": await conversation_service.list_conversations(user_id, last_update_time, last_id, limit,
                                                                scope=scope, origin_article_id=origin_article_id)}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: int, user_id: int, principal: Principal = Depends(require_principal)):
    match_user(principal, user_id)
    return {"data": await conversation_service.get_conversation(conversation_id, user_id)}


@app.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, user_id: int, principal: Principal = Depends(require_principal),
                       limit: int | None = Query(default=None, ge=1, le=50),
                       before: int | None = Query(default=None, gt=0), after: int | None = Query(default=None, gt=0),
                       around: int | None = Query(default=None, gt=0)):
    match_user(principal, user_id)
    await conversation_service.require_owner(conversation_id, user_id)
    if limit is not None:
        from app.services.history_pages import history_pages
        return {'data': await history_pages.page(conversation_id, user_id, limit, before, after, around)}
    if any(value is not None for value in (before, after, around)):
        raise HTTPException(422, '分页游标需要同时指定limit')
    history = await conversation_service.get_history(conversation_id)
    from app.services.run_history import run_history
    history = await run_history.history(conversation_id, user_id, history)
    pending = await run_repository.pending_approval(conversation_id)
    if pending:
        history = [*history, {"role": "assistant", "content": pending["draft"],
                             "interrupted": True, "interruptPayload": pending, "isDraft": True}]
    return {"data": history}


@app.get('/conversations/{conversation_id}/questions')
async def question_index(conversation_id: int, user_id: int, principal: Principal = Depends(require_principal),
                         after: int | None = Query(default=None, gt=0), limit: int = Query(default=200, ge=1, le=500),
                         snapshot: int | None = Query(default=None, gt=0)):
    match_user(principal, user_id)
    await conversation_service.require_owner(conversation_id, user_id)
    from app.services.history_pages import history_pages
    return {'data': await history_pages.questions(conversation_id, after, limit, snapshot)}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user_id: int, principal: Principal = Depends(require_principal)):
    match_user(principal, user_id)
    await conversation_service.require_owner(conversation_id, user_id)
    async with mysql_client.db.transaction():
        await run_repository._lock_conversation(conversation_id, user_id)
        await run_repository.cancel(conversation_id, user_id)
        await conversation_service.delete_conversation(conversation_id)
    return {"status": "ok"}


@app.get("/tools")
async def list_tools(principal: Principal = Depends(require_principal)):
    return [{"name": t.name, "description": t.description} for t in tool_registry.get_all_tools()]


@app.get('/memory')
async def memory_overview(before: int | None = Query(default=None, gt=0),
                          limit: int = Query(default=30, ge=1, le=50),
                          kind: Literal['all', 'constraint', 'decision', 'event'] = 'all',
                          principal: Principal = Depends(require_principal)):
    return await memory_management.overview(principal.user_id, before=before, limit=limit, kind=kind)


@app.put('/memory/profile')
async def edit_memory_profile(edit: ProfileEdit, principal: Principal = Depends(require_principal)):
    await memory_management.save_profile(principal.user_id, edit)
    return {'status': 'ok'}


@app.put('/memory/records/{memory_id}')
async def edit_memory_record(edit: RecordEdit, memory_id: int = Path(gt=0),
                             principal: Principal = Depends(require_principal)):
    await memory_management.change_record(principal.user_id, memory_id, edit.version, edit=edit)
    return {'status': 'ok'}


@app.delete('/memory/records/{memory_id}')
async def remove_memory_record(memory_id: int = Path(gt=0),
                               version: str = Query(pattern=r'^[a-f0-9]{64}$'),
                               principal: Principal = Depends(require_principal)):
    await memory_management.change_record(principal.user_id, memory_id, version)
    return {'status': 'ok'}


class McpReloadRequest(BaseModel):
    servers: dict


@app.post("/mcp/reload")
async def reload_mcp(request: McpReloadRequest):
    raise HTTPException(404, "MCP 配置仅允许通过服务部署更新")


@app.get("/runs/{run_id}")
async def run_status(run_id: UUID, principal: Principal = Depends(require_principal)):
    run = await run_repository.get(str(run_id))
    if not run or run["user_id"] != principal.user_id:
        raise HTTPException(404, "运行不存在")
    await conversation_service.require_owner(run["conversation_id"], principal.user_id)
    return await reconciled_run_status(run, principal.user_id)


@app.get('/conversations/{conversation_id}/run')
async def conversation_run(conversation_id: int, principal: Principal = Depends(require_principal)):
    await conversation_service.require_owner(conversation_id, principal.user_id)
    run = await run_repository.latest(conversation_id, principal.user_id)
    return await reconciled_run_status(run, principal.user_id) if run else None


@app.get('/run-overview')
async def run_overview(principal: Principal = Depends(require_principal)):
    rows = await run_repository.overview(principal.user_id)
    items = []
    for row in rows:
        # Reconcile expired leases and interrupted saves just as the detail API
        # does. Do not expose result_json, execution tokens or draft contents.
        status = row
        if row['status'] in ('running', 'awaiting_approval'):
            try:
                status = await run_service.reconcile_saved(row)
                await run_repository.expire_existing(row['conversation_id'], principal.user_id, row['run_id'])
                status = await run_repository.get(row['run_id'])
            except HTTPException as error:
                if error.status_code == 404: continue  # Conversation deleted during the poll.
                raise
            if not status: continue
        items.append({'runId': row['run_id'], 'conversationId': str(row['conversation_id']),
                      'title': row['title'], 'status': status['status'],
                      'updatedAt': status['updated_at'].isoformat() + 'Z'})
    return {'items': items, 'serverTime': datetime.now(UTC).isoformat().replace('+00:00', 'Z')}


async def reconciled_run_status(run, uid):
    from app.services.run_service import public_run_result
    run = await run_service.reconcile_saved(run)
    if run["status"] in ("running", "awaiting_approval"):
        await run_repository.expire_existing(run["conversation_id"], uid, run["run_id"])
        run = await run_repository.get(run["run_id"])
    recoverable = RunService.recovery_candidate(run)
    return {"runId": run["run_id"], "conversationId": str(run['conversation_id']), "status": run["status"],
            "recoverable": recoverable,
            "draftHash": run["draft_hash"], "deadline": run["deadline"].isoformat() + 'Z',
            "result": public_run_result(run["result_json"]),
            "draftArticleId": str(run["draft_article_id"]) if run["draft_article_id"] else None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
