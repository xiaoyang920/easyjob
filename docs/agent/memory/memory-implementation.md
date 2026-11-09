# 自定义 Memory 实现指南

Python agent 独立部署时，Java 只传 `user_id`、`conversation_id`、`message`，不传 `history_messages`。
Python 自己管理对话历史：Redis 缓存 + 滑动窗口截断，对应 Java 的 `AiConversationService`。

---

## 第零步：`app/clients/redis_client.py` 改成异步

`memory.py` 在 `async def` 接口里调用，Redis IO 必须用异步客户端，否则会阻塞事件循环。
`redis.asyncio` 是 `redis-py` 内置模块，不需要额外安装，API 和同步版完全一样。

```python
"""
Redis 客户端（异步版）
对应 Java: RedisComponent.java
"""
import redis.asyncio as aioredis

from app.config import settings


class RedisClient:
    def __init__(self):
        self.client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        await self.client.set(key, value, ex=ex)

    async def delete(self, key: str):
        await self.client.delete(key)
```

---

## 第一步：新建 `app/services/memory.py`

```python
"""
对话记忆服务
对应 Java: AiConversationService（Redis + 滑动窗口部分）
"""
import json
from app.clients.redis_client import RedisClient

MAX_ROUNDS = 20        # 最多保留 N 轮，和 Java agent.conversation.max-rounds 保持一致
TTL_SECONDS = 7200     # Redis 过期时间 2 小时


class ConversationMemory:
    def __init__(self):
        self._redis = RedisClient()

    def _key(self, conversation_id: int) -> str:
        return f"py_conversation:{conversation_id}"

    def _truncate(self, messages: list[dict]) -> list[dict]:
        """
        滑动窗口截断，和 Java truncateContext 逻辑一致：
        - system 消息始终保留
        - 非 system 消息保留最近 MAX_ROUNDS * 2 条（一轮 = 一问一答）
        """
        keep = MAX_ROUNDS * 2
        system = [m for m in messages if m.get("role") == "system"]
        others = [m for m in messages if m.get("role") != "system"]
        if len(others) > keep:
            others = others[-keep:]
        return system + others

    async def get(self, conversation_id: int) -> list[dict]:
        """读取会话历史，不存在返回空列表"""
        data = await self._redis.get(self._key(conversation_id))
        return json.loads(data) if data else []

    async def add(self, conversation_id: int, role: str, content: str):
        """追加一条消息，自动截断，刷新过期时间"""
        messages = await self.get(conversation_id)
        messages.append({"role": role, "content": content})
        messages = self._truncate(messages)
        await self._redis.set(
            self._key(conversation_id),
            json.dumps(messages, ensure_ascii=False),
            ex=TTL_SECONDS,
        )

    async def clear(self, conversation_id: int):
        """清除会话（开始新对话）"""
        await self._redis.delete(self._key(conversation_id))
```

---

## 第二步：改造 `app/main.py`

### ChatRequest 去掉 history_messages

```python
class ChatRequest(BaseModel):
    """聊天请求"""
    user_id: int
    conversation_id: int | None = None
    message: str
    # history_messages 去掉，Python 自己从 Redis 读
```

### 模块级单例

```python
from app.services.memory import ConversationMemory

memory = ConversationMemory()
graph = create_agent_graph()   # graph 也移到模块级，避免每次请求重建
```

### /chat 接口

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    conv_id = request.conversation_id or 0

    # 从 Redis 读历史
    history = memory.get(conv_id) if conv_id else []

    initial_state: AgentState = {
        "user_message": request.message,
        "history_messages": history,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }

    result = await graph.ainvoke(initial_state)
    reply = result["final_reply"]

    # 写回 Redis
    if conv_id:
        memory.add(conv_id, "user", request.message)
        memory.add(conv_id, "assistant", reply)

    return ChatResponse(reply=reply, conversation_id=conv_id)
```

### /chat/stream 接口

```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    conv_id = request.conversation_id or 0
    history = memory.get(conv_id) if conv_id else []

    initial_state: AgentState = {
        "user_message": request.message,
        "history_messages": history,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }

    full_reply = []

    async def generate():
        async for event in graph.astream_events(initial_state, version="v2"):
            if event["event"] == "on_chat_model_stream" \
                    and event["metadata"].get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield f"data: {json.dumps({'content': chunk})}\n\n"

        # 流结束后保存
        if conv_id:
            memory.add(conv_id, "user", request.message)
            memory.add(conv_id, "assistant", "".join(full_reply))

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## 第三步：新增清除会话接口（可选）

```python
@app.delete("/conversation/{conversation_id}")
def clear_conversation(conversation_id: int):
    memory.clear(conversation_id)
    return {"status": "ok"}
```

---

## Java 调用侧改动

Java `AgentService` 不再从 Redis 读 history、不再传 `historyMessages`，改成：

```java
// 只传必要参数
Map<String, Object> body = new HashMap<>();
body.put("user_id", userId);
body.put("conversation_id", conversationId);
body.put("message", userMessage);

// 调 Python agent 接口
String reply = httpClient.post("/chat", body);
```

Python agent 自己负责 memory，Java 只负责：
- 创建/管理会话 ID
- 持久化到 MySQL（如果还需要的话）
- 把 Python 返回的 reply 展示给前端

---

## Redis Key 命名

| Key | 含义 |
|---|---|
| `py_conversation:{id}` | Python agent 管理的对话历史 |

注意加了 `py_` 前缀，避免和 Java 侧的 Redis key 冲突（Java 用的是 `conversation:{id}`）。
