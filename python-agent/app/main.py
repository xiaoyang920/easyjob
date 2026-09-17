"""
FastAPI 入口
对应 Java: AgentController + AgentService
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime

from langgraph.types import Command
from fastapi import FastAPI
from pydantic import BaseModel, Field
import asyncio

from starlette.responses import StreamingResponse

from app.clients import mysql_client
from app.clients.mcp_client import mcp_manager
from app.config import settings
from app.graph.builder import  get_graph
from app.graph.state import AgentState
from app.services.conversation import ConversationService
from app.services.image_understanding import preprocess_message
from app.services.logging_config import setup_logging, get_logger, set_request_trace, truncate
from app.services.memory import memory_service
from app.services.tool_registry import tool_registry

# 初始化日志（必须在其他模块大量打日志之前）
setup_logging(level="INFO")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时连接 MySQL + 检查 ES 索引，关闭时断开"""
    await mysql_client.startup()

    # 检查并创建 user_memories 索引
    from app.clients.es_client import BaseEsClient
    es = BaseEsClient()
    await es.ensure_user_memories_index()
    #mcp
    server_configs = json.loads(settings.MCP_SERVERS_JSON)
    if server_configs:
        await mcp_manager.connect(server_configs)
        tool_registry.refresh()

    yield
    await mcp_manager.shutdown()
    await mysql_client.shutdown()
app = FastAPI(title="EasyJob Python Agent", lifespan=lifespan)
conversation_service = ConversationService()
class ChatRequest(BaseModel):
    """聊天请求 - 对应 Java: AiChatParam"""
    user_id: int
    conversation_id: int | None = None
    message: str
    image_paths: list[str] | None = None
def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])

class ChatResponse(BaseModel):
    """聊天响应 - 对应 Java: AiChatVO"""
    model_config = {"alias_generator": _to_camel, "populate_by_name": True}
    reply: str
    conversation_id: str           # → JSON 输出 conversationId
    articles: list[dict] = Field(default_factory=list)
class ResumeRequest(BaseModel):
    """Human-in-the-loop 恢复请求"""
    user_id: int
    conversation_id: int
    action: str                     # 用户的决策，如 "approve" / "reject" / 自由文本

# Worker 节点名 → 进度协议名的映射
NODE_TO_PROGRESS = {
    "planner":          "planner",
    "search_worker":    "search",
    "chat_worker":      "chat",
    "analysis_worker":  "analysis",
    "writing_worker":   "writing",
    "synthesizer":      "synthesizer",
}

def _sse(data: str) -> str:
    """SSE 编码：将真实换行转义为 \\n，避免 Java SSE 中间层重编码丢失换行"""
    return f"data:{data.replace(chr(10), '\\n')}\n\n"
@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    非流式聊天（完整流程）

    【流程】
    1. 无 conversation_id → 创建新会话
    2. ConversationService 取历史并截断
    3. 组装 state，调图执行
    4. 保存 user + assistant 消息到 MySQL
    5. 返回结果

    【Checkpointer 在这里做了什么？】
    - 图内每个节点执行后自动保存快照到 Redis
    - 如果某个节点调了 interrupt()，图会暂停，本接口返回中断信息
    - 恢复时走 /chat/resume 接口
    """
    graph = await get_graph()
    #1.会话管理
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)
    #2.构建上下文
    context = await conversation_service.get_context_for_llm(conv_id)
    await conversation_service.add_message(conv_id, "user", request.message, image_paths=request.image_paths)
    #2.5 图片预处理：GLM-4V 转文字描述
    processed_message = await preprocess_message(request.message, request.image_paths)
    #3.组装 state
    initial_state: AgentState = {
        "user_message": processed_message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
        "cancelled": False,
    }
    #4.执行图
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    result = await graph.ainvoke(initial_state, config=config)
    
   #5.检查是否被interrupt暂停
    state = await graph.aget_state(config)
    interrupt_payload = None
    if state.tasks:
        for task in state.tasks:
            if task.interrupts:
                interrupt_payload = task.interrupts[0].value
                break
    if state.next and interrupt_payload is not None:
        return ChatResponse(
            reply=json.dumps({
                "interrupted": True,
                "pending_node": list(state.next),
                "payload": interrupt_payload,
            }, ensure_ascii=False),
            conversation_id=str(conv_id),
        )
    # 6. 正常完成 → 保存消息
    reply = result.get("final_reply", "抱歉，处理出错了")
    await conversation_service.add_message(conv_id, "assistant", reply)

    return ChatResponse(reply=reply, conversation_id=str(conv_id))
@app.post("/chat/resume", response_model=ChatResponse)
async def chat_resume(request: ResumeRequest):
    """
    从被打断的节点开始恢复然后再执行，并行的话会等所有节点都完成后才会暂停
    """
    graph = await get_graph()
    conv_id = request.conversation_id
    config = {"configurable":{"thread_id":f"conv_{conv_id}"}}
    #Command恢复执行
    result = await graph.ainvoke(Command(resume=request.action),config)
    state = await graph.aget_state(config)
    interrupt_payload = None
    if state.tasks:
        for task in state.tasks:
            if task.interrupts:
                interrupt_payload = task.interrupts[0].value
                break
    if state.next and interrupt_payload is not None:
        return ChatResponse(
            reply=json.dumps({
                "interrupted": True,
                "pending_node": list(state.next),
                "payload": interrupt_payload,
            }, ensure_ascii=False),
            conversation_id=str(conv_id),
        )
    reply = result.get("final_reply", "抱歉，处理出错了")
    await conversation_service.add_message(conv_id, "assistant", reply)
    return ChatResponse(reply=reply, conversation_id=str(conv_id))


@app.post("/chat/resume/stream")
async def chat_resume_stream(request: ResumeRequest):
    """
    流式版 resume：从被打断的节点恢复执行，SSE 推送进度和内容
    """
    graph = await get_graph()
    conv_id = request.conversation_id
    set_request_trace(conv_id)
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    full_reply: list[str] = []

    log.info("/chat/resume/stream 入口 | conv=%s action=%r",
             conv_id, truncate(str(request.action), 200))

    async def generate():
        yield _sse(f"__CONV_ID__:{conv_id}")
        started_nodes: set[str] = set()
        finished_nodes: set[str] = set()

        async for event in graph.astream_events(
            Command(resume=request.action), config=config, version="v2"
        ):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")

            if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                started_nodes.add(node)
                if node == "synthesizer":
                    yield _sse("__PROGRESS__:synthesizer")

            if kind == "on_chain_end" and node in NODE_TO_PROGRESS and node not in finished_nodes:
                finished_nodes.add(node)

            if kind == "on_chat_model_stream" \
                    and event.get("metadata", {}).get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield _sse(chunk)

        # 检查是否又被 interrupt
        state = await graph.aget_state(config)
        interrupt_payload = None
        if state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break
        if state.next and interrupt_payload is not None:
            yield _sse(f"__INTERRUPTED__:{json.dumps(interrupt_payload, ensure_ascii=False)}")
        else:
            yield _sse("__PROGRESS__:done")

        # 从 state 取草稿 id
        final_state_for_draft = await graph.aget_state(config)
        draft_article_id = (
            final_state_for_draft.values.get("draft_article_id")
            if final_state_for_draft else None
        )

        if draft_article_id:
            draft_title = ""
            for wr in final_state_for_draft.values.get("worker_results", []):
                if wr.get("draft_article_id") == draft_article_id:
                    draft_title = wr.get("draft_title", "") or ""
                    break
            yield _sse(
                "__DRAFT_SAVED__:" + json.dumps({
                    "draftArticleId": str(draft_article_id),
                    "title": draft_title,
                }, ensure_ascii=False)
            )

        reply_text = "".join(full_reply)
        if reply_text:
            await conversation_service.add_message(
                conv_id, "assistant", reply_text,
                draft_article_id=draft_article_id,     # ← 新增
            )
        if reply_text and not (state.next and interrupt_payload is not None):
            all_messages = await conversation_service.get_history(conv_id)
            if await memory_service.should_extract(
                    conversation_id=conv_id,
                    messages=all_messages,
                    assistant_text=reply_text,
                    interrupted=False,
            ):
                await memory_service.mark_extract_scheduled(conv_id)
                asyncio.create_task(
                    memory_service.extract_and_store(request.user_id, conv_id, all_messages)
                )
        yield _sse(json.dumps({'conversationId': str(conv_id)}))
        yield _sse("[DONE]")

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/chat/{conversation_id}/cancel")
async def cancel_chat(conversation_id: int):
    """
    用户暂停：把 cancelled=True 写入图的 state，
    后续节点检查到 flag 后会跳过执行。
    """
    graph = await get_graph()
    config = {"configurable": {"thread_id": f"conv_{conversation_id}"}}
    await graph.aupdate_state(config, {"cancelled": True})
    return {"status": "ok"}


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = await get_graph()
    #判断是否是新会话
    is_new_conversation = request.conversation_id is None

    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)
    #1.先读历史消息
    context = await conversation_service.get_context_for_llm(conv_id)
    await conversation_service.add_message(conv_id, "user", request.message, image_paths=request.image_paths)
    # 图片预处理：GLM-4V 转文字描述
    processed_message = await preprocess_message(request.message, request.image_paths)
    #判断是否需要提取用户习惯
    if memory_service.should_recall(is_new_conversation,request.message):
        memory_context = await memory_service.recall(request.user_id,processed_message,top_k=3)
        if memory_context:
            context.insert(0,{"role":"system","content":memory_context})
    #初始化state
    initial_state: AgentState = {
        "user_id": request.user_id,
        "user_message": processed_message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "required_skills": [],
        "worker_results": [],
        "article_cards": [],
        "citations": [],
        "final_reply": "",
        "cancelled": False,
        "needs_retry": False,
        "retry_count": 0,
        "reflection_feedback": "",
        "draft_article_id": None,
    }
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    full_reply: list[str] = []

    set_request_trace(conv_id)
    log.info("/chat/stream 入口 | user=%s conv=%s new=%s msg=%r",
             request.user_id, conv_id, is_new_conversation, truncate(request.message, 200))

    async def generate():
        # 先推会话 ID，让前端尽早拿到
        yield _sse(f"__CONV_ID__:{conv_id}")
        # 追踪已经发过进度事件的节点，避免重复
        started_nodes: set[str] = set()
        finished_nodes: set[str] = set()
        active_workers: list[str] = []  # planner 输出的 worker 列表

        async for event in graph.astream_events(initial_state, config= config,version="v2"):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")

            # ────── 节点开始 → 推进度 ──────
            if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                started_nodes.add(node)

                if node == "planner":
                    yield _sse("__PROGRESS__:planner")

                elif node == "synthesizer":
                    yield _sse("__PROGRESS__:synthesizer")

                elif node in ("search_worker", "chat_worker", "analysis_worker", "writing_worker"):
                    # 第一个 worker 开始时，一次性发 dispatcher 进度
                    if "dispatcher" not in started_nodes:
                        started_nodes.add("dispatcher")
                        # 从 state 读 planner 输出的 active_workers
                        state_snapshot = await graph.aget_state(config)
                        if state_snapshot and state_snapshot.values:
                            active_workers = state_snapshot.values.get("active_workers", [])
                        workers_str = ",".join(active_workers) if active_workers else node.replace("_worker", "")
                        yield _sse(f"__PROGRESS__:dispatcher:{workers_str}")

            # ────── 节点结束 ──────
            if kind == "on_chain_end" and node in NODE_TO_PROGRESS and node not in finished_nodes:
                finished_nodes.add(node)

            # ────── synthesizer 的 LLM 流式输出 → 推内容 ──────
            if kind == "on_chat_model_stream" \
                    and event.get("metadata", {}).get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield _sse(chunk)

            # 全部完成
        # 检查是否被 interrupt 暂停（writing_worker 等节点调了 interrupt()）
        state = await graph.aget_state(config)
        # 并行场景下 tasks 可能有多个，需要遍历找到有 interrupt 数据的那个
        interrupt_payload = None
        if state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break
        if state.next and interrupt_payload is not None:
            # 真正的 interrupt（审批场景），推送中断事件给前端
            yield _sse(f"__INTERRUPTED__:{json.dumps(interrupt_payload, ensure_ascii=False)}")
        else:
            yield _sse("__PROGRESS__:done")
        #这里有疑问，这里如果打断是否要结束
        # 从 checkpointer 读最终 state，取卡片（旁路数据）
        final_state = await graph.aget_state(config)
        article_cards = final_state.values.get("article_cards", []) if final_state else []

        # 去重
        seen_ids = set()
        unique_cards = []
        for card in article_cards:
            aid = card.get("articleId")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                unique_cards.append(card)

        if unique_cards:
            yield _sse(f"__ARTICLES__:{json.dumps(unique_cards, ensure_ascii=False)}")


        # 从 state 取草稿 id（writing_worker 或 synthesizer 写进去的）
        draft_article_id = final_state.values.get("draft_article_id") if final_state else None

        # 如果有草稿 → 先发一条 SSE 事件给前端
        if draft_article_id:
            draft_title = ""
            # 从 worker_results 里兜底拿一次 title
            for wr in final_state.values.get("worker_results", []):
                if wr.get("draft_article_id") == draft_article_id:
                    draft_title = wr.get("draft_title", "") or ""
                    break
            yield _sse(
                "__DRAFT_SAVED__:" + json.dumps({
                    "draftArticleId": str(draft_article_id),
                    "title": draft_title,
                }, ensure_ascii=False)
            )

        reply_text = "".join(full_reply)
        await conversation_service.add_message(
            conv_id, "assistant", reply_text,
            article_cards=unique_cards or None,
        )
        if not (state.next and interrupt_payload is not None):
            all_messages = await conversation_service.get_history(conv_id)
            if await memory_service.should_extract(
                    conversation_id=conv_id,
                    messages=all_messages,
                    assistant_text=reply_text,
                    interrupted=False,
            ):
                await memory_service.mark_extract_scheduled(conv_id)
                asyncio.create_task(
                    memory_service.extract_and_store(request.user_id, conv_id, all_messages)
                )

        yield _sse(json.dumps({'conversationId': str(conv_id)}))
        yield _sse("[DONE]")

    return StreamingResponse(generate(), media_type="text/event-stream")
@app.get("/conversations")
async def list_conversations(
    user_id: int,
    last_update_time: datetime | None = None,
    last_id: int | None = None,
    limit: int = 10,
):
    """会话列表（游标分页）"""
    convs = await conversation_service.list_conversations(user_id, last_update_time, last_id, limit)
    return {"data": convs}

@app.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int):
    """获取会话历史消息"""
    messages = await conversation_service.get_history(conversation_id)
    return {"data": messages}
@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    """删除会话"""
    await conversation_service.delete_conversation(conversation_id)
    return {"status": "ok"}
@app.get("/tools")
async def list_tools():
    """查看当前 Agent 可用的所有工具（本地 + MCP）"""
    from app.services.tool_registry import tool_registry
    tools = tool_registry.get_all_tools()
    return [{"name": t.name, "description": t.description} for t in tools]
class McpReloadRequest(BaseModel):
    """MCP 热重载请求，传入新的 server 配置"""
    servers: dict  # 和 MCP_SERVERS_JSON 格式一致

@app.post("/mcp/reload")
async def reload_mcp(request: McpReloadRequest):
    """
    运行时热重载 MCP 配置，不用重启服务

    流程: 关闭旧连接 → 用新配置连接 → 刷新 tool_registry
    """
    from app.clients.mcp_client import mcp_manager
    from app.services.tool_registry import tool_registry

    await mcp_manager.reload(request.servers)
    tool_registry.refresh()

    tools = tool_registry.get_all_tools()
    return {
        "status": "ok",
        "tool_count": len(tools),
        "tools": [t.name for t in tools],
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
