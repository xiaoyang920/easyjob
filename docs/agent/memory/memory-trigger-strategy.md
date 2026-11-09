# 长期记忆触发策略（用户画像 + 事件记忆）

> 2026-10-03：历史事件自动提取和召回已关闭；每六轮与关键词触发均已退役。只根据用户明确表达更新画像、约束和已确认决策，旧事件在归档页查看或删除。以下是旧设计记录，不代表当前运行行为；当前规则见[结构化记忆运行说明](23-structured-memory-runtime.md)。

> 当前运行链路已调整（2026-10-01）：每次请求读取结构化画像和有效约束，事件/决策由 Main 按需检索；明确变更在 Main 响应中同步处理。下文是旧触发策略，当前实现以 [结构化记忆运行说明](23-structured-memory-runtime.md) 为准。

> 基于当前 `ConversationService + ai_conversation/ai_message + app/services/memory.py` 的可落地方案。
> 目标：避免“每轮都 recall / extract”的无效开销，同时保留跨会话记忆的价值。
>
> **范围说明（2026-08-21）**：本文是 V1 触发策略，只覆盖“什么时候 recall/extract”。结构化事件类型（constraint/decision/goal）、`user/project` 作用域、状态与冲突替代、规划前与 Task 级两级召回，以 `docs/agent/memory/22-long-term-memory-v2.md` 为准。

---

## 一、当前代码现状

### 1.1 已有能力

- `ConversationService.get_context_for_llm()` 已负责同一会话内的上下文构建：
  - `ai_conversation.summary`
  - `summary_upto_msg_id`
  - 游标后的近期消息
- `MemoryService.extract_and_store()` 已支持一次提取同时产出：
  - `memories`：事件记忆
  - `profile_updates`：用户画像更新
- `MemoryService._store_memory()` 已支持：
  - MySQL 批量插入 `user_memory`
  - ES 批量写入 `user_memories`
- `MemoryService._update_profile()` 已支持画像更新与摘要重生成。

### 1.2 当前缺口

- `app/main.py` 里还没有真正接入 `memory_service.recall()` 和 `memory_service.extract_and_store()`。
- 当前长期记忆逻辑还没有统一触发规则。
- 当前 `profile_updates` 的合并策略里：
  - `preferences`：新值覆盖旧值
  - `experience`：新值覆盖旧值
  - `tech_stack` / `interests`：并集去重，只增不减

### 1.3 为什么不能每轮都触发

如果每次请求都做一次长期记忆召回和提取，会带来几类浪费：

- 同一会话内，短期上下文已经由 `ConversationService` 提供，再做长期召回会重复。
- 每次提取都会额外触发：
  - 一次结构化 LLM 调用
  - 一次或多次 MySQL / ES 写入
  - 一次画像摘要重生成
- `chat_resume` / `chat_resume/stream` 是中断恢复流程，不应该重复做请求前召回。
- 寒暄、确认、客套类消息几乎没有长期记忆价值。

因此，长期记忆必须采用“条件触发 + 异步执行 + 降频”的策略。

---

## 二、设计原则

### 2.1 触发点放在接口层，不放在 Worker 节点里

长期记忆的触发应放在：

- `/chat`
- `/chat/stream`
- `/chat/resume`
- `/chat/resume/stream`

而不是放在：

- `chat_worker`
- `search_worker`
- `synthesizer`

原因：

- Worker 是图内节点，关注点应该是单轮推理，不应该承担跨会话记忆策略。
- 一个请求不一定会走 `chat_worker`，但长期记忆触发应以“整轮对话是否完成”为准。
- 中断恢复、流式输出、并行 worker 都应该由接口层统一收口。

### 2.2 区分短期上下文与长期记忆

- 短期上下文：由 `ConversationService` 负责，同一会话内始终可见。
- 长期记忆：只用于跨会话、跨主题的稳定偏好和高价值结论。

因此：

- 同一会话内的普通追问，不需要每轮都做长期召回。
- 长期召回主要解决“新会话开始”或“用户显式引用历史偏好”这类场景。

### 2.3 事件记忆和用户画像分开考虑

虽然当前 `extract_and_store()` 一次会同时产出 `memories` 和 `profile_updates`，但触发逻辑应区分两类信号：

- **事件记忆**：更适合“按轮次”或“会话收口”触发
- **用户画像**：更适合“显式偏好/身份信号”触发

最终实现上仍可以共用一次 `extract_and_store()`，但触发条件不应只看轮次。

---

## 三、推荐触发规则

## 3.1 Recall：什么时候召回长期记忆

### 推荐规则

只在以下场景召回长期记忆：

- **新会话开始时**
  - `conversation_id is None`
  - 或该会话消息很少，仍处于起始阶段
- **用户显式引用历史或偏好时**
  - 例如：
    - “你还记得我之前说的吗”
    - “按我之前的习惯回答”
    - “继续上次的话题”
    - “根据我的背景给建议”
- **用户问题明显依赖长期画像时**
  - 例如：
    - “我适合学什么”
    - “结合我的技术栈推荐一下”

### 不建议召回的场景

- 同一会话里的普通连续问答
- `chat_resume` / `chat_resume/stream`
- 仅是确认、寒暄、补充一两句

### 原因

因为当前同一会话内已经有：

- `summary`
- `summary_upto_msg_id`
- 游标后的未总结消息

这已经能覆盖绝大多数“记住上文”的需求。

### 默认建议

- `top_k = 3`
- 只在 `/chat`、`/chat/stream` 的图执行前判断是否召回
- 不在 `resume` 接口做召回

---

## 3.2 Extract：什么时候提取长期记忆

### 统一触发点

提取应放在“assistant 消息最终保存之后”，也就是：

- `/chat`：`await conversation_service.add_message(conv_id, "assistant", reply)` 之后
- `/chat/stream`：流结束并保存 assistant 后
- `/chat/resume`：恢复执行完成并保存 assistant 后
- `/chat/resume/stream`：恢复流结束并保存 assistant 后

### 必须满足的前置条件

只有以下条件都满足时，才允许进入提取判断：

- 本轮没有停在 `interrupt`
- assistant 最终回复非空
- 当前回合不是纯寒暄/确认类低价值对话

### 低价值对话跳过规则

以下场景默认跳过提取：

- 用户消息很短，且不包含偏好/身份信息
- assistant 回复很短，只是礼貌收尾
- 典型低价值文本：
  - “好的”
  - “收到”
  - “谢谢”
  - “嗯嗯”
  - “ok”

### 触发方式采用“双轨制”

#### 规则 A：显式画像信号，立即触发

如果用户消息中出现明显的“自我描述 / 偏好 / 长期要求”信号，则本轮结束后立即触发提取。

典型信号包括：

- “我是…”
- “我做…”
- “我用…”
- “我平时…”
- “我一般…”
- “我喜欢…”
- “以后默认…”
- “以后都按这个风格…”
- “记住…”
- “别再用…”
- “请默认用…”

这类信息价值高，而且如果等到第 6 轮再提取，容易丢失。

#### 规则 B：事件记忆按固定轮次触发

对于普通问题求解、检索、讨论类对话，不需要每轮提取事件记忆，建议：

- **每 6 轮用户消息触发一次**
- 或者更保守一点：**每 8 轮用户消息触发一次**

推荐默认值：

- `EXTRACT_INTERVAL_TURNS = 6`

### 规则 C：空闲结束兜底触发

如果会话在一段时间内没有新消息，可以补一次“收口提取”：

- 空闲 `10~15` 分钟
- 将最近未提取的一段对话做一次提取

这条规则不是首期必须实现，但推荐作为后续补强。

### 规则 D：同一会话加节流

即使满足规则 A 或 B，也建议增加节流：

- 同一会话 `5` 分钟内最多提取一次

推荐默认值：

- `EXTRACT_COOLDOWN_SECONDS = 300`

这样可以防止：

- 高频短问短答重复提取
- 流式 + 恢复场景短时间内重复触发

---

## 3.3 Profile：用户画像的更新规则

### 触发原则

用户画像不应该靠“每轮都更新”来维护，而应该只在存在稳定用户信息时更新：

- 身份信息：
  - “我是 Java 后端”
  - “我做内容平台”
- 技术栈：
  - “我现在主要用 Spring Boot / LangGraph”
- 偏好：
  - “以后回答简洁点”
  - “优先给我代码，不要讲太多理论”
- 经验水平：
  - “我还是初学者”
  - “我做了很多年后端”

### 当前代码下的推荐策略

- `preferences`：允许立即覆盖旧值
- `experience`：最后一个有效值覆盖旧值
- `tech_stack` / `interests`：
  - 首期仍沿用现有“并集去重”逻辑
  - 但只在存在强信号时才更新

### 已知问题

当前 `tech_stack` / `interests` 的实现是：

```python
list(set(old + new))
```

这会导致：

- 旧标签只会越来越多
- 用户习惯变化后，历史标签无法自然删除

### 结论

首期不建议靠“高频提取”来解决这个问题，应该通过“降低更新频率 + 只在强信号时更新”先把噪音降下来。

后续如果确实需要支持“偏好改变”，再考虑：

- 给标签加 `last_seen`
- 做衰减/淘汰
- 或把画像拆成更细的事实表

---

## 3.4 Event：事件记忆的更新规则

### 适合进入 `memories` 的内容

只保留这些：

- 本轮达成的明确结论
- 用户已经确认的方案
- 具有复用价值的事实
- 对后续对话有帮助的事件信息

例如：

- “用户本次决定采用 Python Agent 独立管理会话”
- “本轮确认长期记忆提取不应每轮执行，而采用固定轮次 + 结束兜底”

### 不应进入 `memories` 的内容

- 寒暄
- 一次性问题细节
- 未确认的试错过程
- 临时情绪表达
- 大段工具原始结果
- 文章卡片列表本身

### 推荐限制

每次提取最多保留：

- `1 ~ 3` 条事件记忆

避免把一次长对话拆成十几条低质量碎片。

---

## 四、推荐接入点

## 4.1 在 `/chat` 和 `/chat/stream` 前判断是否 recall

判断逻辑：

- 新会话，或
- 用户消息命中长期记忆信号

如果命中，则：

```python
memory_context = await memory_service.recall(request.user_id, processed_message, top_k=3)
```

然后把 `memory_context` 作为 system 上下文插入 `context` 最前面。

## 4.2 在 assistant 保存后判断是否 extract

统一在以下位置判断：

- `/chat` 保存 assistant 后
- `/chat/stream` 流结束保存 assistant 后
- `/chat/resume` 保存 assistant 后
- `/chat/resume/stream` 流结束保存 assistant 后

如果命中提取条件，则：

```python
asyncio.create_task(
    memory_service.extract_and_store(user_id, conv_id, all_messages)
)
```

注意：

- 必须异步执行
- 不能阻塞主响应
- 不能在 `interrupt` 中间态就触发

---

## 五、首期建议实现

## 5.1 先实现这四条

### 规则 1

**`recall` 只在新会话或显式历史引用时触发**

### 规则 2

**`extract_and_store` 只在 assistant 完整回复保存后触发**

### 规则 3

**显式画像信号立即提取**

### 规则 4

**普通事件记忆每 6 轮提取一次，并加 5 分钟节流**

## 5.2 暂时不做

首期可以先不做：

- 空闲结束提取
- 标签衰减 / 删除
- 复杂的偏好冲突解决
- 细粒度多策略提取器拆分

---

## 六、伪代码示例

```python
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


def has_profile_signal(text: str) -> bool:
    return any(k in text for k in PROFILE_SIGNAL_PATTERNS)


def has_history_signal(text: str) -> bool:
    return any(k in text for k in HISTORY_SIGNAL_PATTERNS)


def is_low_value_round(user_text: str, assistant_text: str) -> bool:
    if user_text.strip() in LOW_VALUE_PATTERNS:
        return True
    if len(user_text.strip()) <= 6 and len(assistant_text.strip()) <= 20:
        return True
    return False


async def should_recall(is_new_conversation: bool, user_text: str) -> bool:
    if is_new_conversation:
        return True
    if has_history_signal(user_text):
        return True
    if has_profile_signal(user_text):
        return True
    return False


async def should_extract(
    user_text: str,
    assistant_text: str,
    user_turn_count: int,
    interrupted: bool,
    in_cooldown: bool,
) -> bool:
    if interrupted:
        return False
    if not assistant_text.strip():
        return False
    if is_low_value_round(user_text, assistant_text):
        return False
    if in_cooldown:
        return False
    if has_profile_signal(user_text):
        return True
    if user_turn_count % EXTRACT_INTERVAL_TURNS == 0:
        return True
    return False
```

---

## 七、最终结论

推荐方案不是：

- 每轮都 recall
- 每轮都 extract

而是：

- **Recall：新会话 / 显式历史引用时触发**
- **Profile：显式偏好或身份信号时立即触发**
- **Event：按固定轮次低频触发**
- **Extract：统一放在 assistant 最终保存后异步执行**
- **Resume：不做 recall，只在最终完成后参与 extract 判断**

这套策略最符合你当前代码结构：

- 不和 `ConversationService` 的短期上下文重复
- 不把长期记忆逻辑绑死在 `chat_worker`
- 不会把每轮对话都变成高成本后处理
- 后续也容易平滑扩展到“结束兜底”和“画像衰减”
