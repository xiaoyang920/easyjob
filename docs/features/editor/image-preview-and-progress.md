# 图片预览放大 & 图片理解阶段提示

> 此文记录旧版 GLM 图片描述流程，已由 [DeepSeek 原生图片输入](../../agent/runtime/native-image-input.md) 替代。当前图片随用户问题直接进入 Main，没有独立的 GLM 识图阶段，下面的 `preprocess_message` 接口及进度改造示例不再适用。

## 一、图片点击放大（已完成）

`AiChat.vue` 中用户发送的图片原来是普通 `<img>` 标签，不支持点击放大。

改为 Element Plus 的 `<el-image>`：

```vue
<el-image 
  v-if="msg.image" 
  :src="msg.image" 
  :preview-src-list="[msg.image]"
  class="message-image" 
  alt="用户图片"
  fit="contain"
  :preview-teleported="true"
/>
```

`preview-src-list` 启用点击预览，`preview-teleported` 将弹层挂到 body 防止被遮挡。

---

## 二、图片理解阶段提示

### 问题

用户发送图片后，Python 端需要调用 GLM-4.6V 做图片理解（可能耗时 5-15 秒），这段时间前端没有任何反馈，体验差。

### 方案：在 SSE 流中新增 `__PROGRESS__:image_understanding` 事件

#### 2.1 Python 端修改（main.py `chat_stream`）

在 `generate()` 开始处，图片预处理前后各发一个进度事件：

```python
async def generate():
    yield _sse(f"__CONV_ID__:{conv_id}")
    
    # ========== 新增：图片理解阶段 ==========
    nonlocal processed_message  # 需要改结构，把 preprocess_message 挪到 generate 内部
    if request.image_paths:
        yield _sse("__PROGRESS__:image_understanding")
        processed_message = await preprocess_message(request.message, request.image_paths)
    # ========================================
    
    # 更新 initial_state 的 user_message
    initial_state["user_message"] = processed_message
    
    # ... 后续 planner/worker/synthesizer 流程不变
```

**注意**：需要把 `preprocess_message` 调用从 `chat_stream` 函数体挪到 `generate()` 内部，这样才能在 SSE 流中发进度事件。当前代码是在 `generate()` 外面先处理好图片再进入流，所以前端拿不到任何反馈。

修改后的 `chat_stream` 结构：

```python
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = await get_graph()
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)
    await conversation_service.add_message(conv_id, "user", request.message, image_paths=request.image_paths)
    context = await conversation_service.get_context_for_llm(conv_id)
    
    # 不再在这里做 preprocess_message，移到 generate() 内部
    initial_state: AgentState = {
        "user_message": request.message,  # 先放原始消息，generate 里替换
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    full_reply: list[str] = []
    
    async def generate():
        yield _sse(f"__CONV_ID__:{conv_id}")
        
        # 图片理解阶段（在 SSE 流内部，前端可以收到进度）
        if request.image_paths:
            yield _sse("__PROGRESS__:image_understanding")
            processed = await preprocess_message(request.message, request.image_paths)
            initial_state["user_message"] = processed
        
        # ... 后续 astream_events 不变
```

#### 2.2 前端修改（AiChat.vue）

##### 2.2.1 进度步骤条增加图片理解步骤

在 `handleProgress` 函数中处理新事件：

```typescript
} else if (progressData === 'image_understanding') {
    // 图片理解步骤
    const steps = messages.value[aiMsgIndex].progressSteps || []
    steps.push({
        key: 'image_understanding',
        label: '正在识别图片...',
        status: 'active'
    })
    messages.value[aiMsgIndex].progressSteps = steps
    
} else if (progressData === 'planner') {
    // planner 开始说明图片理解已完成，更新状态
    const steps = messages.value[aiMsgIndex].progressSteps || []
    const imgStep = steps.find(s => s.key === 'image_understanding')
    if (imgStep) {
        imgStep.status = 'done'
        imgStep.label = '图片识别完成'
    }
    // ... 原有 planner 逻辑
```

##### 2.2.2 NODE_TO_PROGRESS 映射（Python 端可选）

如果想保持一致性，也可以在 Python 的 `NODE_TO_PROGRESS` 中加：
```python
NODE_TO_PROGRESS = {
    "image_understanding": "image_understanding",  # 新增
    "planner":          "planner",
    ...
}
```
但图片理解不是图节点，不需要加到这个映射里。直接在 `generate()` 顶部手动 yield 即可。

---

## 三、非流式接口（/chat）

非流式接口没有 SSE 没法发进度。如果也需要感知，前端可以在调用前自行显示"正在识别图片..."的 loading 状态，等请求返回后清除。不需要后端配合。
