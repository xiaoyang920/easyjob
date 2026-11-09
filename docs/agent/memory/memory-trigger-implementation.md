# 长期记忆触发具体实现方案

> 2026-10-03：历史事件自动提取和召回已关闭；每六轮与关键词触发均已退役。只根据用户明确表达更新画像、约束和已确认决策，旧事件在归档页查看或删除。以下是旧设计记录，不代表当前运行行为；当前规则见[结构化记忆运行说明](23-structured-memory-runtime.md)。

> 当前运行方式（2026-10-01）：每次请求读取独立画像和有效约束，历史事件/决策由 Main 的 `retrieve(memory)` 按需召回；明确变更通过 `memory_changes` 事务提交。本文后续的入口自动召回描述属于旧实现，当前合同以 [结构化记忆运行说明](23-structured-memory-runtime.md) 为准。

> 基于当前项目已有代码：
> - `app/main.py`
> - `app/services/memory.py`
> - `app/services/conversation.py`
>
> 目标不是重写架构，而是在现有 `ConversationService + LangGraph + MemoryService` 上，把长期记忆的 `recall` / `extract` **真正接入**，并避免“每轮都触发”的浪费。
>
> **状态说明（2026-08-21）**：文中“`main.py` 还没接长期记忆”已过时，流式主链路与流式 resume 已接入 recall/extract，非流式 `/chat`、`/chat/resume` 仍未接入。V2 数据模型与分层召回以 `docs/agent/memory/22-long-term-memory-v2.md` 为准。

---

## 一、先说最终要实现成什么样

### 1.1 `/chat` 和 `/chat/stream`

每次新请求的流程改成：

1. 创建会话（如果没有 `conversation_id`）
2. 先读取**当前会话已有上下文**：`conversation_service.get_context_for_llm(conv_id)`
3. 做图片预处理，拿到 `processed_message`
4. 判断是否需要 `recall`
5. 如果需要，则调用 `memory_service.recall()`，把长期记忆作为 `system` 上下文插到 `context` 最前面
6. 保存本轮 user 消息到 `ai_message`
7. 执行图
8. 保存 assistant 消息
9. 判断是否需要 `extract`
10. 如果需要，则后台异步 `extract_and_store()`

### 1.2 `/chat/resume` 和 `/chat/resume/stream`

恢复接口不做 `recall`，只做收口时的 `extract`：

1. 直接恢复执行
2. 如果又被 `interrupt`，直接返回，不提取
3. 如果正常完成，保存 assistant 消息
4. 判断是否需要 `extract`
5. 如果需要，后台异步 `extract_and_store()`

### 1.3 为什么这样最贴合你现在的代码

因为你当前项目已经天然分成两层：

- **短期上下文**：`ConversationService.get_context_for_llm()`
- **长期记忆提取/画像更新**：`MemoryService`

所以：

- **短期上下文**继续走 `ConversationService`
- **长期记忆触发策略**放在接口层
- **Worker 节点不改**

这样改动最小，也最不容易把现有图逻辑搞乱。

---

## 二、当前代码里必须先认清的两个事实

## 2.1 `main.py` 目前还没真正接上长期记忆

我看了你当前 `app/main.py`：

- 没有 `memory_service.recall()`
- 没有 `memory_service.extract_and_store()`

所以现在的长期记忆只是“服务层能力已经写了”，但**还没进主流程**。

## 2.2 `/chat` 和 `/chat/stream` 现在有顺序不一致的问题

### `/chat`

当前顺序是：

1. `get_context_for_llm(conv_id)`
2. `add_message(user)`
3. 图执行

这没问题，因为 `history_messages` 里不会重复带上当前这一轮 user 消息。

### `/chat/stream`

当前顺序是：

1. `add_message(user)`
2. `get_context_for_llm(conv_id)`
3. 图执行

这会导致一个问题：

- 当前 user 消息已经进 DB
- `get_context_for_llm()` 又把它读回来了
- 同时 `initial_state["user_message"]` 里也有当前消息

结果就是**当前用户消息被重复注入了一次**。

### 结论

在接长期记忆前，应该先把 `/chat/stream` 的顺序改成和 `/chat` 一样：

1. 先读旧上下文
2. 再保存当前 user 消息
3. 再执行图

这个改动要一起写进文档，不然后面接 `recall` 时会把问题放大。

## 2.3 `recall` 和 `decay` 的 ES/MySQL 数据不一致

当前代码有一个**真实缺陷**：ES 和 MySQL 的职责混用，导致状态不一致。

### 现状

| 操作 | MySQL | ES |
|------|-------|----|
| 写入记忆 (`_store_memory`) | ✅ 写入 | ✅ 写入（含 `importance`） |
| 召回 (`recall`) | ❌ 不读 | ✅ 直接读 `_source` 当最终结果 |
| 更新访问计数 | ✅ `access_count + 1` | ❌ 不更新 |
| 衰减 (`decay`) | ✅ 降低 `importance` | ❌ 不更新 |
| 遗忘删除 | ✅ `DELETE` | ❌ 不删除 |

### 会出什么问题

- **[缺陷1]** `importance` 在 MySQL 衰减了，但 ES 里还是旧值 → 召回时看到的重要性是过期的
- **[缺陷2]** MySQL 删除了低价值记忆，但 ES 里文档还在 → **已经"遗忘"的记忆仍然会被 ES 检索出来**（幽灵记忆）
- **[缺陷3]** `access_count` 只在 MySQL，ES 完全不知道 → 无法在 ES 侧做基于访问频次的排序

### 首期修复方案：MySQL 做真相源，ES 只做检索候选

不做 ES 双写同步（写放大太大），而是改数据流：

1. **`_search_memories()`**：ES 只返回 `memory_id` + 相似度 `score`
2. **`recall()`**：拿到候选 `memory_id` 列表后，去 MySQL 批量查最新 `content`、`importance`、`access_count`
3. **`decay()`**：MySQL 删除低价值记忆后，同步删除对应 ES 文档

这样：

- ES 不需要维护热计数和衰减后的 importance
- MySQL 始终是最新状态
- 不会出现幽灵记忆
- 写入时 ES 里的 `importance` 可以保留（初始值），但**不再被当作最终值使用**

---

## 三、首期实现范围

首期只做这几件事：

- 新会话 / 显式历史引用时做 `recall`
- assistant 完整保存后做 `extract`
- 显式画像信号立即触发提取
- 普通事件记忆每 6 轮提取一次
- 同一会话 5 分钟节流一次
- **修复 recall 数据流：ES 查候选 → MySQL 查真相**
- **修复 decay 遗忘：MySQL 删除后同步删 ES**

首期暂时不做：

- 空闲 15 分钟自动补提取
- 标签衰减 / last_seen
- 用户画像删除旧标签
- 更复杂的多阶段提取器

---

## 四、文件改动清单

本方案只要求改两个文件：

- `app/services/memory.py`
- `app/main.py`

`app/services/conversation.py` 首期不需要新增接口，直接复用：

- `get_context_for_llm()`：给图执行用
- `get_history()`：给记忆提取判断和 `extract_and_store()` 用

---

## 五、`app/services/memory.py` 的具体改法

## 5.1 新增 Redis 节流能力

你当前 `RedisClient` 已经有：

- `get()`
- `set(ex=...)`
- `delete()`

这已经足够做“同一会话 5 分钟内最多提取一次”的节流，不需要新表。

### 在 `memory.py` 顶部补充常量

```python
from app.clients.redis_client import RedisClient

PROFILE_SIGNAL_PATTERNS = [
    "记住", "以后默认", "以后都", "我一般", "我平时", "我喜欢",
    "我是", "我做", "我用", "别再", "请默认",
]

HISTORY_SIGNAL_PATTERNS = [
    "你还记得", "按我之前", "继续上次", "根据我的背景", "根据我的偏好",
]

LOW_VALUE_PATTERNS = [
    "好的", "收到", "谢谢", "嗯嗯", "ok", "OK",
]

EXTRACT_INTERVAL_TURNS = 6
EXTRACT_COOLDOWN_SECONDS = 300
```

### 在 `MemoryService.__init__()` 里补 Redis 客户端

```python
class MemoryService:
    def __init__(self):
        self._embedding = EmbeddingService()
        self._es = BaseEsClient()
        self._llm = get_llm(temperature=0.3)
        self._redis = RedisClient()
```

---

## 5.2 在 `memory.py` 里新增触发判断方法

首期建议把触发判断也放在 `MemoryService` 里，别散落在 `main.py`。

### 建议新增这些方法

```python
def has_profile_signal(self, text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in PROFILE_SIGNAL_PATTERNS)


def has_history_signal(self, text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in HISTORY_SIGNAL_PATTERNS)


def is_low_value_round(self, user_text: str, assistant_text: str) -> bool:
    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if user_text in LOW_VALUE_PATTERNS:
        return True
    if len(user_text) <= 6 and len(assistant_text) <= 20:
        return True
    return False


def should_recall(self, is_new_conversation: bool, user_text: str) -> bool:
    if is_new_conversation:
        return True
    if self.has_history_signal(user_text):
        return True
    if self.has_profile_signal(user_text):
        return True
    return False


def _extract_cooldown_key(self, conversation_id: int) -> str:
    return f"py_mem_extract:{conversation_id}"


async def in_extract_cooldown(self, conversation_id: int) -> bool:
    data = await self._redis.get(self._extract_cooldown_key(conversation_id))
    return bool(data)


async def mark_extract_scheduled(self, conversation_id: int):
    await self._redis.set(
        self._extract_cooldown_key(conversation_id),
        "1",
        ex=EXTRACT_COOLDOWN_SECONDS,
    )


def _find_last_user_text(self, messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _count_user_turns(self, messages: list[dict]) -> int:
    return sum(1 for msg in messages if msg.get("role") == "user")


async def should_extract(
    self,
    conversation_id: int,
    messages: list[dict],
    assistant_text: str,
    interrupted: bool,
) -> bool:
    if interrupted:
        return False
    if not assistant_text.strip():
        return False

    last_user_text = self._find_last_user_text(messages)
    if self.is_low_value_round(last_user_text, assistant_text):
        return False

    if await self.in_extract_cooldown(conversation_id):
        return False

    if self.has_profile_signal(last_user_text):
        return True

    user_turn_count = self._count_user_turns(messages)
    if user_turn_count > 0 and user_turn_count % EXTRACT_INTERVAL_TURNS == 0:
        return True

    return False
```

### 为什么首期用 `get_history()` 来判断轮次

因为你现在 `ConversationService.get_history()` 已经能拿到完整消息列表，首期直接拿它来：

- 找最近一条 user 消息
- 统计 user turn 数

够用了。

这样可以避免首期为了一个计数逻辑，再去改 `ConversationService` 增加额外 SQL。

后续如果担心性能，再补一个 `get_conversation_meta()` 专门返回 `message_count`。

---

## 5.3 修复 `recall` 数据流：ES 查候选 → MySQL 查真相

当前代码的问题（见 2.3 节）：

- `_search_memories()` 直接把 ES 的 `_source` 当最终结果
- `recall()` 直接用 ES 的 `importance`，但它可能已经被 MySQL 衰减
- 已被 MySQL 删除的记忆仍会被 ES 检索到

### 改法：`_search_memories()` 只返回 `memory_id` + `score`

```python
async def _search_memories(
    self, user_id: int, query: str, top_k: int = 5
) -> list[dict]:
    """向量搜索用户记忆，只返回候选 memory_id 和相似度 score"""
    try:
        query_vector = await self._embedding.aembed(query)
        resp = await self._es.client.search(
            index="user_memories",
            knn={
                "field": "content_vector",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": top_k * 3,
                "filter": {"term": {"user_id": user_id}},
            },
            _source=["memory_id"],  # 只要 memory_id，不要其他字段
            size=top_k,
        )
        results = []
        for hit in resp.get("hits", {}).get("hits", []):
            results.append({
                "memory_id": hit["_source"]["memory_id"],
                "score": hit["_score"],
            })
        return results
    except Exception as e:
        log.warning("记忆检索失败: %s", e)
        return []
```

### 改法：`recall()` 拿候选 ID 后去 MySQL 查真相

```python
async def recall(self, user_id: int, query: str, top_k: int = 5) -> str:
    # 1. ES 向量检索，只拿候选 memory_id
    candidates = await self._search_memories(user_id, query, top_k)

    # 2. 获取用户画像
    profile = await self._get_profile(user_id)
    profile_summary = profile.get("summary", "暂无用户画像") if profile else "新用户，暂无画像"

    if not candidates and profile_summary in ("暂无用户画像", "新用户，暂无画像"):
        return ""  # 无有效信息，不注入无用的 system prompt

    # 3. 拿候选 ID 去 MySQL 查最新数据
    relevant_memories = []
    if candidates:
        memory_ids = [c["memory_id"] for c in candidates]
        placeholders = ", ".join(f":id{i}" for i in range(len(memory_ids)))
        params = {f"id{i}": mid for i, mid in enumerate(memory_ids)}

        rows = await db.fetch_all(
            f"SELECT memory_id, content, importance, access_count "
            f"FROM user_memory WHERE memory_id IN ({placeholders})",
            params,
        )
        # 如果 MySQL 里已经不存在（被 decay 删了），就自然过滤掉了
        relevant_memories = [dict(r._mapping) for r in rows]

        # 4. 更新访问计数（只对 MySQL 里还存在的）
        if relevant_memories:
            alive_ids = [m["memory_id"] for m in relevant_memories]
            alive_ph = ", ".join(f":aid{i}" for i in range(len(alive_ids)))
            alive_params = {f"aid{i}": mid for i, mid in enumerate(alive_ids)}
            await db.execute(
                f"UPDATE user_memory SET access_count = access_count + 1 "
                f"WHERE memory_id IN ({alive_ph})",
                alive_params,
            )

    # 5. 格式化输出
    if not relevant_memories:
        mem_text = "无相关历史记忆"
    else:
        mem_text = "\n".join(
            f"- {m['content']} (重要性: {m['importance']:.1f})"
            for m in relevant_memories
        )

    return MEMORY_CONTEXT_TEMPLATE.format(
        profile_summary=profile_summary,
        relevant_memories=mem_text,
    )
```

### 这样改的核心点

- ES **只做向量检索**，返回候选 ID
- MySQL **才是真相源**，返回最新的 `content`、`importance`、`access_count`
- 已被 `decay()` 删除的记忆，MySQL 查不到，自然就过滤掉了
- `main.py` 里的用法不变，还是 `if memory_context: context.insert(...)`

---

## 5.4 修复 `decay()` 同步删除 ES

当前 `decay()` 只删 MySQL，ES 里的幽灵文档还在。

虽然 5.3 里改了 `recall()` 会去 MySQL 查真相，已经能过滤掉幽灵记忆，但 ES 里堆积大量无效文档会：

- 浪费向量检索的候选名额
- 报废文档占用索引空间

所以应该在 `decay()` 删除 MySQL 后同步删 ES。

### 建议改法

```python
async def decay(self, user_id: int, decay_factor: float = 0.95):
    # 1. 衰减低访问记忆的重要性
    await db.execute(
        """
        UPDATE user_memory 
        SET importance = importance * :factor, update_time = :now
        WHERE user_id = :uid 
          AND access_count < 3
          AND importance > 0.1
        """,
        {"factor": decay_factor, "now": datetime.now(), "uid": user_id},
    )

    # 2. 找出要删除的记忆 ID
    to_delete = await db.fetch_all(
        "SELECT memory_id FROM user_memory WHERE user_id = :uid AND importance < 0.1",
        {"uid": user_id},
    )
    delete_ids = [row["memory_id"] for row in to_delete]

    # 3. 删除 MySQL
    if delete_ids:
        placeholders = ", ".join(f":id{i}" for i in range(len(delete_ids)))
        params = {f"id{i}": mid for i, mid in enumerate(delete_ids)}
        await db.execute(
            f"DELETE FROM user_memory WHERE memory_id IN ({placeholders})",
            params,
        )

        # 4. 同步删除 ES
        try:
            actions = [
                {"_op_type": "delete", "_index": "user_memories", "_id": str(mid)}
                for mid in delete_ids
            ]
            await async_bulk(self._es.client, actions, raise_on_error=False)
            log.info("记忆遗忘同步删除 ES: user=%s, count=%d", user_id, len(delete_ids))
        except Exception as e:
            log.warning("遗忘同步删除 ES 失败: %s", e)

    log.info("记忆衰减完成: user=%s, factor=%.2f, deleted=%d", user_id, decay_factor, len(delete_ids))
```

### 这里的核心点

- 先查出要删的 `memory_id`，再删 MySQL，再删 ES
- ES 删除用 `async_bulk` 批量操作，不是一条一条删
- ES 删除失败不影响主流程（只打日志），因为 5.3 里的 `recall()` 已经以 MySQL 为准

---

## 六、`app/main.py` 的具体接法

## 6.1 先补导入和单例

在 `app/main.py` 顶部补：

```python
from app.services.memory import memory_service
```

你现在已经有：

- `conversation_service = ConversationService()`

所以长期记忆继续走模块级单例就行，不需要额外工厂。

---

## 6.2 改 `/chat`

### 当前问题

`/chat` 当前顺序基本是对的，但还没接长期记忆。

### 推荐改法

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    graph = await get_graph()

    is_new_conversation = request.conversation_id is None
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)

    # 1. 先取旧上下文（不包含当前这轮 user）
    context = await conversation_service.get_context_for_llm(conv_id)

    # 2. 当前输入预处理
    processed_message = await preprocess_message(request.message, request.image_paths)

    # 3. recall
    if memory_service.should_recall(is_new_conversation, request.message):
        memory_context = await memory_service.recall(request.user_id, processed_message, top_k=3)
        if memory_context:
            context.insert(0, {"role": "system", "content": memory_context})

    # 4. 再保存当前 user 消息
    await conversation_service.add_message(
        conv_id,
        "user",
        request.message,
        image_paths=request.image_paths,
    )

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
    result = await graph.ainvoke(initial_state, config=config)

    state = await graph.aget_state(config)
    interrupt_payload = None
    if state.tasks:
        for task in state.tasks:
            if task.interrupts:
                interrupt_payload = task.interrupts[0].value
                break

    if state.next and interrupt_payload is not None:
        return ChatResponse(
            reply=json.dumps(
                {
                    "interrupted": True,
                    "pending_node": list(state.next),
                    "payload": interrupt_payload,
                },
                ensure_ascii=False,
            ),
            conversation_id=str(conv_id),
        )

    reply = result.get("final_reply", "抱歉，处理出错了")
    await conversation_service.add_message(conv_id, "assistant", reply)

    # 5. assistant 落库后，判断是否提取长期记忆
    all_messages = await conversation_service.get_history(conv_id)
    if await memory_service.should_extract(
        conversation_id=conv_id,
        messages=all_messages,
        assistant_text=reply,
        interrupted=False,
    ):
        await memory_service.mark_extract_scheduled(conv_id)
        asyncio.create_task(
            memory_service.extract_and_store(request.user_id, conv_id, all_messages)
        )

    return ChatResponse(reply=reply, conversation_id=str(conv_id))
```

### 为什么这里一定要“先取上下文，再保存当前 user”

因为当前 user 消息已经单独放在：

```python
"user_message": processed_message
```

所以 `history_messages` 里不应该再重复塞一次。

---

## 6.3 改 `/chat/stream`

### 先修当前顺序 bug

你现在的 `/chat/stream` 是：

1. 先 `add_message(user)`
2. 再 `get_context_for_llm(conv_id)`

这个要改成和 `/chat` 一致。

### 推荐改法

```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = await get_graph()

    is_new_conversation = request.conversation_id is None
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)

    # 1. 先读旧上下文
    context = await conversation_service.get_context_for_llm(conv_id)

    # 2. 当前输入预处理
    processed_message = await preprocess_message(request.message, request.image_paths)

    # 3. recall
    if memory_service.should_recall(is_new_conversation, request.message):
        memory_context = await memory_service.recall(request.user_id, processed_message, top_k=3)
        if memory_context:
            context.insert(0, {"role": "system", "content": memory_context})

    # 4. 再保存当前 user 消息
    await conversation_service.add_message(
        conv_id,
        "user",
        request.message,
        image_paths=request.image_paths,
    )

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
    full_reply: list[str] = []

    async def generate():
        yield _sse(f"__CONV_ID__:{conv_id}")
        started_nodes: set[str] = set()
        finished_nodes: set[str] = set()
        active_workers: list[str] = []

        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")

            if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                started_nodes.add(node)
                if node == "planner":
                    yield _sse("__PROGRESS__:planner")
                elif node == "synthesizer":
                    yield _sse("__PROGRESS__:synthesizer")
                elif node in ("search_worker", "chat_worker", "analysis_worker", "writing_worker"):
                    if "dispatcher" not in started_nodes:
                        started_nodes.add("dispatcher")
                        state_snapshot = await graph.aget_state(config)
                        if state_snapshot and state_snapshot.values:
                            active_workers = state_snapshot.values.get("active_workers", [])
                        workers_str = ",".join(active_workers) if active_workers else node.replace("_worker", "")
                        yield _sse(f"__PROGRESS__:dispatcher:{workers_str}")

            if kind == "on_chain_end" and node in NODE_TO_PROGRESS and node not in finished_nodes:
                finished_nodes.add(node)

            if kind == "on_chat_model_stream" and event.get("metadata", {}).get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield _sse(chunk)

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

        final_state = await graph.aget_state(config)
        article_cards = final_state.values.get("article_cards", []) if final_state else []

        seen_ids = set()
        unique_cards = []
        for card in article_cards:
            aid = card.get("articleId")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                unique_cards.append(card)

        if unique_cards:
            yield _sse(f"__ARTICLES__:{json.dumps(unique_cards, ensure_ascii=False)}")

        reply_text = "".join(full_reply)
        await conversation_service.add_message(
            conv_id,
            "assistant",
            reply_text,
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

        yield _sse(json.dumps({"conversationId": str(conv_id)}))
        yield _sse("[DONE]")

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 这一段的关键点

- 先读 context，再存 user
- `recall` 只做一次
- `extract` 放在流结束、assistant 落库之后
- 若本轮真的停在 `interrupt`，就不触发提取

---

## 6.4 改 `/chat/resume`

恢复接口不需要再 `recall`，因为：

- 它不是新会话
- 它不是新的用户提问
- 它只是把之前被打断的执行接着跑完

### 推荐改法

在当前 `/chat/resume` 成功保存 assistant 后，补：

```python
reply = result.get("final_reply", "抱歉，处理出错了")
await conversation_service.add_message(conv_id, "assistant", reply)

all_messages = await conversation_service.get_history(conv_id)
if await memory_service.should_extract(
    conversation_id=conv_id,
    messages=all_messages,
    assistant_text=reply,
    interrupted=False,
):
    await memory_service.mark_extract_scheduled(conv_id)
    asyncio.create_task(
        memory_service.extract_and_store(request.user_id, conv_id, all_messages)
    )

return ChatResponse(reply=reply, conversation_id=str(conv_id))
```

### 注意

如果当前 `resume` 后又再次进入 `interrupt`，那仍然按原逻辑直接返回中断响应，**不要触发提取**。

---

## 6.5 改 `/chat/resume/stream`

和 `/chat/resume` 一样：

- 不做 `recall`
- 只在真正流完成、assistant 落库之后做 `extract` 判断

### 推荐改法

在这段后面补：

```python
reply_text = "".join(full_reply)
if reply_text:
    await conversation_service.add_message(conv_id, "assistant", reply_text)

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
```

---

## 七、为什么这里首期不改 `ConversationService`

虽然从架构上讲，可以在 `ConversationService` 里再加：

- `get_conversation_meta()`
- `get_latest_user_message()`
- `get_user_turn_count()`

但首期没必要。

因为你当前已经有两个现成接口：

- `get_context_for_llm()`：图执行用
- `get_history()`：提取判断和提取本体都能用

首期直接复用这两个方法，文档最贴当前代码，也最容易先跑起来。

后续如果担心：

- `get_history()` 数据量大
- 每次提取判断都要扫全量消息

再把计数和最近 user 消息查询抽成轻量 SQL 即可。

---

## 八、这版实现和你现有 `memory.py` 的兼容关系

你当前的 `memory.py` 已经有这些能力：

- `extract_and_store()`
- 批量写 `user_memory`
- 批量写 ES
- `_update_profile()`
- `_regenerate_summary()`

所以这次接入时**不需要改提取主流程**，只需要补：

- 触发判断
- recall 空结果降噪
- Redis 节流

换句话说：

- 事件记忆怎么存，你已经有了
- 用户画像怎么更新，你已经有了
- 现在差的是“什么时候该触发”

---

## 九、建议的日志埋点

为了验证这套触发规则，建议在 `memory.py` 和 `main.py` 加几条日志。

## 9.1 recall

```python
log.info(
    "长期记忆 recall: conv=%s, new=%s, hit=%s",
    conv_id,
    is_new_conversation,
    bool(memory_context),
)
```

## 9.2 extract skip reason

在 `should_extract()` 里按分支打 debug 日志，例如：

- `skip: interrupted`
- `skip: empty_reply`
- `skip: low_value_round`
- `skip: cooldown`
- `hit: profile_signal`
- `hit: interval_turn`

这样你后面调试看日志一眼就知道为什么没提取。

---

## 十、联调检查清单

按下面顺序测：

## 10.1 `/chat_stream` 不再重复注入当前 user 消息

检查点：

- 当前 user 消息只出现在 `user_message`
- 不再同时出现在 `history_messages` 里

## 10.2 新会话会触发 recall

场景：

- 新建一个 conversation
- 用户问“结合我的背景，推荐下学习路线”

期望：

- `should_recall()` 命中
- 如果历史画像存在，则注入 system memory context

## 10.3 同会话普通追问不做 recall

场景：

- 连续问第 2、3 轮普通问题

期望：

- 不触发 recall

## 10.4 显式偏好会立即触发 extract

场景：

- 用户说“以后回答尽量简洁，多给代码”

期望：

- 本轮 assistant 保存后，立即后台提取
- `profile_updates.preferences` 被更新

## 10.5 普通问题按第 6 轮触发 extract

场景：

- 连续进行一般问答

期望：

- 第 1~5 轮不提取
- 第 6 轮保存 assistant 后触发一次提取

## 10.6 中断态不提取

场景：

- `writing_worker` 触发 `interrupt`

期望：

- 当前轮不做 extract
- `resume` 完成后再判断是否提取

---

## 十一、这版是首期最合适的实现

这版实现的核心特点是：

- **不改 Worker**
- **不改图结构**
- **不改 `ConversationService` 主职责**
- **只在 `main.py` 收口处接长期记忆**
- **只在 `memory.py` 补触发判断和节流**

所以它非常适合你现在这个项目阶段：

- 改动小
- 成本可控
- 行为可解释
- 后面再演进也容易

最终效果就是：

- 不是每轮都 `recall`
- 不是每轮都 `extract`
- 用户画像和事件记忆都能接入
- 不会和现有 `ConversationService` 的短期上下文打架

---

## 十二、后续第二阶段再做什么

等首期跑顺后，再考虑这些升级：

- 空闲超时兜底提取
- `tech_stack` / `interests` 的衰减和淘汰
- 画像更新从“并集去重”升级为“带 last_seen 的事实表”
- 给 `ConversationService` 增加轻量 meta 查询接口
- 事件记忆去重
- 画像摘要重生成降频
