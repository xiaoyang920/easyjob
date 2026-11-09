# Bug：AI回答中切换会话，消息丢失

## 问题描述

在 AI 正在流式回复时，用户点击左侧切换到另一个会话，当前正在生成的 AI 回复会直接消失。切回原来的会话后，消息也找不到了。

## 根因分析

问题涉及 **前端状态管理** 和 **后端消息持久化时机** 两方面：

### 1. 前端：`messages` 是单一数组，切换直接丢弃

```typescript
// switchConversation() — 第491行
currentConversationId.value = conv.conversationId
messages.value = []  // ← 直接清空！正在流式写入的内容全没了
```

`messages` 是组件内唯一的消息数组（`ref<ChatMessage[]>([])`），所有会话共用。切换时 `messages.value = []` 把正在通过 SSE 写入的内容一并清掉了。

### 2. 前端：SSE 通过固定索引写入，数组一换就"写空气"

```typescript
// streamChat() 中的核心逻辑
const aiMsgIndex = messages.value.length - 1  // 记住索引

// SSE 循环里用索引写入
messages.value[aiMsgIndex].content += data.replace(/\\n/g, '\n')
```

切换会话后 `messages.value` 被替换为新会话的消息数组，`aiMsgIndex` 指向的位置要么不存在（越界），要么是另一个会话的消息。

### 3. 后端：消息在流完成后才持久化

```python
# main.py — chat_stream() 的 generate()
reply_text = "".join(full_reply)
if reply_text:
    await conversation_service.add_message(conv_id, "assistant", reply_text)
yield _sse("[DONE]")
```

AI 回复是在 SSE 流结束后才调 `add_message` 存入数据库。如果前端切走中断了连接：
- 前端的 `reader.read()` 不再消费 → Python 的 `StreamingResponse` 会被取消（客户端断开）
- `add_message` 可能**永远不会执行**
- 即使 LLM 已经完整生成了回复，也不会被保存

### 4. 前端：SSE 流没有被中断

`switchConversation()` 没有 abort 当前的 `AbortController`，fetch 连接还活着。SSE 事件继续到达，但此时 `messages.value` 已经是新会话的数据。后续写入可能：
- 乱写到新会话的消息上
- `aiMsgIndex` 越界导致 JS 错误

## 影响范围

| 场景 | 后果 |
|------|------|
| AI 流式生成中切换会话 | 正在生成的回复丢失，不入库 |
| 切回原会话 | 从数据库加载消息，AI 回复不在其中 |
| 用户消息 | 已入库（流开始前保存），但成了"没有回复的孤立消息" |
| 极端情况 | SSE 继续写入新会话的 messages 数组，导致内容错乱 |

## 修复方案

### 方案整体思路

**核心原则**：每个会话独立管理消息 + 切换时正确处理流 + 消息持久化提前/容错。

### 修复点1：会话消息缓存（Map）

用 `Map<conversationId, ChatMessage[]>` 替代单一 `messages` 数组，切换时保存当前、恢复目标。

```typescript
// 声明
const messageCache = new Map<string, ChatMessage[]>()

// 计算属性，自动关联当前会话
const messages = computed({
  get: () => {
    if (!currentConversationId.value) return []
    return messageCache.get(currentConversationId.value) || []
  },
  set: (val) => {
    if (currentConversationId.value) {
      messageCache.set(currentConversationId.value, val)
    }
  }
})
```

**优势**：切换会话不丢数据，切回时无需重新请求 API。

### 修复点2：切换会话时中断当前流

在 `switchConversation()` 中检查是否有进行中的流，abort 并重置状态：

```typescript
async function switchConversation(conv: any) {
  if (currentConversationId.value === conv.conversationId && messages.value.length > 0) {
    return
  }

  // 如果正在流式生成，先中断
  if (streaming.value && currentAbortController) {
    currentAbortController.abort()
    currentAbortController = null
    streaming.value = false
    loading.value = false
  }

  currentConversationId.value = conv.conversationId
  // ... 加载消息
}
```

### 修复点3：SSE 写入前校验会话 ID

在 `streamChat()` 的 SSE 循环中，每次写入前检查当前会话是否还是发起流的那个：

```typescript
async function streamChat(message: string, imagePaths: string[], aiMsgIndex: number) {
  const targetConvId = currentConversationId.value  // 锁定发起时的会话ID
  
  // ... SSE 循环中
  // 写入内容前校验
  if (currentConversationId.value !== targetConvId) {
    reader.cancel()
    return
  }
  messages.value[aiMsgIndex].content += data.replace(/\\n/g, '\n')
}
```

### 修复点4：后端消息持久化容错（可选增强）

在 Python SSE generator 中加 `try/finally`，确保即使客户端断开也能尝试保存：

```python
async def generate():
    yield _sse(f"__CONV_ID__:{conv_id}")
    try:
        async for event in graph.astream_events(...):
            # ... 正常处理
            pass
    except asyncio.CancelledError:
        pass  # 客户端断开
    finally:
        # 无论如何都尝试保存已生成的内容
        reply_text = "".join(full_reply)
        if reply_text:
            await conversation_service.add_message(conv_id, "assistant", reply_text)
        yield _sse("[DONE]")  # 这行在断开时可能发不出去，但不影响
```

> **注意**：`finally` 中的 `yield` 在客户端已断开时不会真的发送，但 `add_message` 仍然会执行，这才是关键。不过 `StreamingResponse` 的 generator 在客户端断开时的行为取决于 ASGI 服务器（uvicorn），`CancelledError` 可能导致 finally 中的异步操作也被取消。更稳妥的做法是用 `asyncio.shield()`：
>
> ```python
> finally:
>     reply_text = "".join(full_reply)
>     if reply_text:
>         await asyncio.shield(
>             conversation_service.add_message(conv_id, "assistant", reply_text)
>         )
> ```

## 推荐实施顺序

| 优先级 | 修复点 | 效果 | 工作量 |
|--------|--------|------|--------|
| P0 | 修复点2：切换时中断流 | 防止乱写 + 清理状态 | 小 |
| P0 | 修复点3：SSE 写入校验 | 防止写错会话 | 小 |
| P1 | 修复点1：消息缓存 Map | 切走不丢数据 | 中 |
| P2 | 修复点4：后端容错保存 | 客户端断开也不丢回复 | 中 |

**P0 两项可以立即实施**，加起来改动不超过 10 行，能解决最核心的问题。P1 是体验优化（切回不需重新加载）。P4 是完整性保障。
