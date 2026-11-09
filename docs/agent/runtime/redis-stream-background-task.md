# Redis Stream 后台任务架构 — 切换会话不中断生成

## 背景

当前 SSE 流与 LangGraph 执行绑定在同一个 async generator 里。前端切换会话 → SSE 断开 → generator 被取消 → 图执行中断 → AI 回复丢失。

**目标**：前端切走后，后端继续生成并把结果写入 Redis Stream；前端切回来时可以重新读取。

## 整体架构

```
┌─────────┐   POST /chat/stream    ┌──────────────┐    XADD     ┌──────────────┐
│  前端    │ ───────────────────→   │  FastAPI      │ ─────────→ │ Redis Stream │
│ (Vue)   │                        │  启动Task     │            │  chat:{id}   │
└────┬────┘                        │  立即返回SSE  │            └──────┬───────┘
     │                             └──────────────┘                   │
     │  GET /chat/stream/{id}           ↑                             │
     │  (SSE 读取器)                    │ asyncio.Task 后台跑         │
     │ ─────────────────────→    ┌──────┴──────────┐    XADD         │
     │                           │  GraphTask      │ ────────────────┘
     │  ← SSE events ──         │  astream_events │
     │                           │  → Redis Stream │
     │  切走/断开                │  (不受影响)     │
     │                           │  完成→存MySQL   │
     │  切回来                   │  完成→标记DONE  │
     │  GET /chat/stream/{id}   └─────────────────┘
     │  ← 从头回放 + 继续       
     └──────────────────
```

## Redis Stream Key 设计

```
Key:     chat:stream:{conversation_id}
TTL:     10 分钟（完成后设置，自动清理）
```

每条消息的字段：

| field   | 说明 | 示例 |
|---------|------|------|
| `type`  | 事件类型 | `conv_id` / `progress` / `content` / `interrupted` / `articles` / `meta` / `done` |
| `data`  | 事件内容 | 具体数据 |

示例：
```
XADD chat:stream:12345 * type conv_id data "12345"
XADD chat:stream:12345 * type progress data "planner"
XADD chat:stream:12345 * type progress data "dispatcher:search,analysis"
XADD chat:stream:12345 * type content data "Spring Boot是..."
XADD chat:stream:12345 * type content data "一个Java框架"
XADD chat:stream:12345 * type progress data "done"
XADD chat:stream:12345 * type meta data '{"conversationId":"12345"}'
XADD chat:stream:12345 * type done data ""
```

## 需要改的文件

### 1. `app/clients/redis_client.py` — 增加 Stream 操作

```python
# 新增方法

async def xadd(self, key: str, fields: dict, maxlen: int = 500):
    """追加一条消息到 Stream"""
    await self.client.xadd(key, fields, maxlen=maxlen)

async def xread_all(self, key: str, start: str = "0-0") -> list:
    """从 start 位置读取所有已有消息"""
    result = await self.client.xrange(key, min=start)
    return result  # [(msg_id, {field: value}), ...]

async def xread_block(self, key: str, last_id: str, block_ms: int = 2000) -> list:
    """阻塞读取新消息"""
    result = await self.client.xread({key: last_id}, block=block_ms, count=10)
    if not result:
        return []
    # result 格式: [[key, [(msg_id, fields), ...]]]
    return result[0][1]

async def expire(self, key: str, seconds: int):
    await self.client.expire(key, seconds)

async def exists(self, key: str) -> bool:
    return await self.client.exists(key) > 0
```

### 2. `app/services/task_manager.py` — 新建，后台任务管理

```python
"""
后台任务管理器
- 将图执行从 HTTP 连接中解耦
- 结果写入 Redis Stream
- 完成后持久化到 MySQL
"""
import asyncio
import json
from app.clients.redis_client import redis_client
from app.services.conversation import ConversationService

conversation_service = ConversationService()

# 活跃任务注册表：{conversation_id: asyncio.Task}
_active_tasks: dict[int, asyncio.Task] = {}

def _stream_key(conv_id: int) -> str:
    return f"chat:stream:{conv_id}"

async def _push_event(conv_id: int, event_type: str, data: str = ""):
    """写一条事件到 Redis Stream"""
    await redis_client.xadd(
        _stream_key(conv_id),
        {"type": event_type, "data": data}
    )

async def run_graph_task(
    conv_id: int,
    graph,
    initial_state: dict,
    config: dict,
):
    """
    后台执行图，结果实时写入 Redis Stream。
    由 asyncio.create_task() 启动，不依赖任何 HTTP 连接。
    """
    stream_key = _stream_key(conv_id)
    full_reply: list[str] = []
    started_nodes: set[str] = set()
    finished_nodes: set[str] = set()

    NODE_TO_PROGRESS = {
        "planner", "dispatcher",
        "search_worker", "chat_worker", "analysis_worker", "writing_worker",
        "synthesizer",
    }

    try:
        await _push_event(conv_id, "conv_id", str(conv_id))

        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")

            # 进度事件
            if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                started_nodes.add(node)
                if node == "planner":
                    await _push_event(conv_id, "progress", "planner")
                elif node == "synthesizer":
                    await _push_event(conv_id, "progress", "synthesizer")
                elif node in ("search_worker", "chat_worker", "analysis_worker", "writing_worker"):
                    if "dispatcher" not in started_nodes:
                        started_nodes.add("dispatcher")
                        state_snapshot = await graph.aget_state(config)
                        active_workers = []
                        if state_snapshot and state_snapshot.values:
                            active_workers = state_snapshot.values.get("active_workers", [])
                        workers_str = ",".join(active_workers) if active_workers else node.replace("_worker", "")
                        await _push_event(conv_id, "progress", f"dispatcher:{workers_str}")

            if kind == "on_chain_end" and node in NODE_TO_PROGRESS and node not in finished_nodes:
                finished_nodes.add(node)

            # synthesizer 流式内容
            if kind == "on_chat_model_stream" \
                    and event.get("metadata", {}).get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    await _push_event(conv_id, "content", chunk)

        # 检查 interrupt
        state = await graph.aget_state(config)
        interrupt_payload = None
        if state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break

        if state.next and interrupt_payload is not None:
            await _push_event(conv_id, "interrupted", json.dumps(interrupt_payload, ensure_ascii=False))
        else:
            await _push_event(conv_id, "progress", "done")

        # 持久化
        reply_text = "".join(full_reply)
        if reply_text:
            await conversation_service.add_message(conv_id, "assistant", reply_text)

        await _push_event(conv_id, "meta", json.dumps({"conversationId": str(conv_id)}))
        await _push_event(conv_id, "done", "")

    except asyncio.CancelledError:
        # 被 cancel 接口取消
        reply_text = "".join(full_reply)
        if reply_text:
            await conversation_service.add_message(conv_id, "assistant", reply_text)
        await _push_event(conv_id, "progress", "done")
        await _push_event(conv_id, "done", "")
    except Exception as e:
        await _push_event(conv_id, "error", str(e))
        await _push_event(conv_id, "done", "")
    finally:
        # 10 分钟后自动清理 Stream
        await redis_client.expire(stream_key, 600)
        _active_tasks.pop(conv_id, None)


def start_task(conv_id: int, graph, initial_state: dict, config: dict) -> asyncio.Task:
    """启动后台任务"""
    # 如果该会话已有运行中的任务，先取消
    old_task = _active_tasks.get(conv_id)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(run_graph_task(conv_id, graph, initial_state, config))
    _active_tasks[conv_id] = task
    return task


def is_running(conv_id: int) -> bool:
    """检查某个会话是否有正在执行的任务"""
    task = _active_tasks.get(conv_id)
    return task is not None and not task.done()


def cancel_task(conv_id: int):
    """取消任务"""
    task = _active_tasks.get(conv_id)
    if task and not task.done():
        task.cancel()
```

### 3. `app/main.py` — 改造 `/chat/stream` 端点

**改造前**：generate() 里直接跑 graph，SSE 断了 graph 跟着停。

**改造后**：

```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = await get_graph()
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)
    await conversation_service.add_message(conv_id, "user", request.message, image_paths=request.image_paths)
    context = await conversation_service.get_context_for_llm(conv_id)
    processed_message = await preprocess_message(request.message, request.image_paths)

    initial_state: AgentState = {
        "user_message": processed_message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
        "cancelled": False,
    }
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}

    # ① 启动后台任务（不绑定 HTTP 连接）
    task_manager.start_task(conv_id, graph, initial_state, config)

    # ② SSE 只负责从 Redis Stream 读事件推给前端
    return StreamingResponse(
        _read_stream(conv_id),
        media_type="text/event-stream"
    )


async def _read_stream(conv_id: int):
    """
    SSE 读取器：从 Redis Stream 读取事件推送给前端。
    断开不影响后台任务。
    """
    stream_key = f"chat:stream:{conv_id}"
    last_id = "0-0"  # 从头开始读

    while True:
        # 先读已有的所有消息（回放）
        messages = await redis_client.xrange(stream_key, min=last_id)

        if not messages:
            # 没有新消息，阻塞等待
            result = await redis_client.xread_block(stream_key, last_id, block_ms=2000)
            if not result:
                # 超时，检查任务是否还在跑
                if not task_manager.is_running(conv_id):
                    # 检查 stream 里是否有 done 标记
                    if await _stream_has_done(stream_key):
                        break
                    # 给一点宽限时间
                    await asyncio.sleep(0.5)
                    if not task_manager.is_running(conv_id):
                        break
                continue
            messages = result

        for msg_id, fields in messages:
            last_id = msg_id
            event_type = fields.get("type", "")
            data = fields.get("data", "")

            if event_type == "done":
                yield _sse("[DONE]")
                return
            elif event_type == "conv_id":
                yield _sse(f"__CONV_ID__:{data}")
            elif event_type == "progress":
                yield _sse(f"__PROGRESS__:{data}")
            elif event_type == "content":
                yield _sse(data)
            elif event_type == "interrupted":
                yield _sse(f"__INTERRUPTED__:{data}")
            elif event_type == "articles":
                yield _sse(f"__ARTICLES__:{data}")
            elif event_type == "meta":
                yield _sse(data)
            elif event_type == "error":
                yield _sse(f"[ERROR]{data}")


async def _stream_has_done(stream_key: str) -> bool:
    """检查 stream 最后一条消息是否是 done"""
    result = await redis_client.client.xrevrange(stream_key, count=1)
    if result:
        _, fields = result[0]
        return fields.get("type") == "done"
    return False
```

### 4. `/chat/resume/stream` 同理改造

把 `generate()` 里的 graph 执行也放到后台任务，SSE 只读 Redis Stream。复用 `task_manager` 和 `_read_stream`。

```python
@app.post("/chat/resume/stream")
async def chat_resume_stream(request: ResumeRequest):
    graph = await get_graph()
    conv_id = request.conversation_id
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}

    # 启动 resume 后台任务
    task_manager.start_resume_task(conv_id, graph, request.action, config)

    return StreamingResponse(
        _read_stream(conv_id),
        media_type="text/event-stream"
    )
```

`task_manager` 中对应增加 `start_resume_task`，内部用 `Command(resume=action)` 替代 `initial_state`。

### 5. 前端改动（`AiChat.vue`，仅描述）

前端基本**不需要大改**，SSE 事件格式没变（`__CONV_ID__`、`__PROGRESS__`、`[DONE]` 等）。

唯一要改的：

1. **`switchConversation()` 中 abort SSE 连接**（已实现），但**不再调 cancel 接口**——切走只是断 SSE，不停后台任务
2. **切回会话时**，如果 Redis Stream 还存在（任务还在跑或刚完成不久），重新发 SSE 请求读取：

```typescript
// switchConversation() 中
const res = await request.get(`/agent/conversations/${conv.conversationId}/messages`)
messages.value = res.data.map(...)

// 检查是否还有正在进行的流
const streamRes = await fetch(`/api/agent/chat/stream/${conv.conversationId}/status`)
if (streamRes.running) {
  // 重连 SSE 读取器，继续接收
  streaming.value = true
  await streamChat_reconnect(conv.conversationId, messages.value.length - 1)
}
```

或者更简单的方案：加一个 `GET /chat/stream/{conv_id}/reconnect` 端点，前端切回后调用，返回的也是 SSE（从 Redis Stream 头开始读），前端直接接着渲染。

### 6. 新增端点：查询任务状态 + 重连

```python
@app.get("/chat/stream/{conversation_id}/status")
async def stream_status(conversation_id: int):
    """查询某个会话的生成任务是否还在跑"""
    running = task_manager.is_running(conversation_id)
    stream_exists = await redis_client.exists(f"chat:stream:{conversation_id}")
    return {
        "running": running,
        "streamExists": stream_exists,
    }


@app.get("/chat/stream/{conversation_id}/reconnect")
async def stream_reconnect(conversation_id: int):
    """
    重连 SSE：从 Redis Stream 头开始读。
    如果任务还在跑，会持续推新事件；
    如果已完成，把所有结果一次性推完。
    """
    return StreamingResponse(
        _read_stream(conversation_id),
        media_type="text/event-stream"
    )
```

## 时序图

### 正常流程（不切换）
```
前端                  FastAPI                    后台Task              Redis Stream
 │─POST /chat/stream──→│                           │                      │
 │                      │─start_task()─────────────→│                      │
 │                      │─_read_stream()──────────→ │                      │
 │                      │                           │─XADD conv_id────────→│
 │                      │←──────────────────────────│←─XREAD──────────────│
 │←─SSE: __CONV_ID__───│                           │                      │
 │                      │                           │─XADD progress───────→│
 │←─SSE: __PROGRESS__──│←─────────────────────────│←─XREAD──────────────│
 │                      │                           │─XADD content────────→│
 │←─SSE: content────── │←─────────────────────────│←─XREAD──────────────│
 │                      │                           │─XADD done──────────→│
 │←─SSE: [DONE]────── │←─────────────────────────│←─XREAD──────────────│
 │                      │                           │─add_message(MySQL)   │
```

### 切走再切回
```
前端                  FastAPI                    后台Task              Redis Stream
 │─POST /chat/stream──→│                           │                      │
 │                      │─start_task()─────────────→│                      │
 │←─SSE: 内容流──────── │                           │─XADD content────────→│
 │                      │                           │                      │
 │  [用户切走]          │                           │                      │
 │──abort SSE──→        │  (SSE断开，无所谓)        │                      │
 │                      │                           │─XADD 继续生成───────→│
 │                      │                           │─XADD 继续生成───────→│
 │                      │                           │─XADD done──────────→│
 │  [用户切回来]        │                           │─add_message(MySQL)   │
 │─GET /status─────────→│                           │                      │
 │←─{running:false}─── │                           │                      │
 │─GET messages────────→│                           │                      │
 │←─完整消息列表────── │  (从MySQL读，回复已存好)   │                      │
```

## 注意事项

1. **`redis-py` 版本**：`redis.asyncio` 已经内置 Stream 支持（`xadd`, `xread`, `xrange`），不需要额外安装
2. **Redis Stream 容量**：用 `maxlen=500` 限制，单次对话不会超过这个量
3. **TTL 清理**：任务完成后设 10 分钟 TTL，过期自动删
4. **cancel 接口**：改为取消 `asyncio.Task`（`task.cancel()`），不再是改图的 state。因为 Task 是独立运行的，CancelledError 会在 finally 中保存已生成内容
5. **并发安全**：同一个会话不会同时有两个任务（`start_task` 里先取消旧的）
6. **Java 层不需要改**：Java 只是透传 SSE，格式没变
