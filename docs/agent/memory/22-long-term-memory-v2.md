# 长期记忆 V2：结构化事件、作用域与分层召回

> 文档状态：**历史目标方案，当前实现已部分落地，以下内容不能整体视为已实现**  
> 最后更新：2026-08-21  
> 适用范围：EasyJob Python Agent 的跨会话长期记忆  
> 当前实现基线：`python-agent/app/services/memory.py`  
> 架构依赖：`21-main-agent-subagent-staged-architecture.md`

> 当前补充（2026-10-01）：动态 Main 已实现独立画像/有效约束启动上下文、按需事件/决策召回、明确用户要求的结构化变更、用户/会话范围、active/inactive状态、run幂等回执及索引重试。博客业务不引入项目实体。当前准确实现见 [结构化记忆运行说明](23-structured-memory-runtime.md)；本文 goal、有效期、全量分类、增量提取水位及旧 PlannedTask/阶段规划等仍是历史目标设计，不等于已实现。

本文档用于保存长期记忆下一阶段的统一方案，供后续实现。它不替代短期会话历史、滚动摘要或 LangGraph Checkpoint，也不表示下述 V2 数据模型已经落库。

## 1. 目标与边界

长期记忆需要解决的是跨会话复用，而不是把所有历史对话永久塞入 Prompt。

```text
短期上下文
  = 当前会话摘要 + 摘要游标后的原始消息
  = ConversationService 管理

长期用户画像
  = 技术栈、经验、兴趣、稳定回答偏好
  = user_profile 管理

长期事件记忆
  = 已确认约束、已确认决策、持续目标
  = user_memory / user_memories 管理
```

V2 的核心目标：

1. 用结构化类型区分约束、决策和持续目标。
2. 每条记忆都绑定可信 `user_id`，并区分用户级、项目级作用域。
3. 通过状态和替代关系处理冲突，不静默覆盖历史。
4. 在 Main Agent 规划前召回全局必要信息，计划生成后按 Task 精准召回。
5. ES 只负责向量候选，MySQL 作为授权与最新状态的事实源。
6. 长期记忆使用独立 `memory_context`，不伪装成普通用户消息。

不在 V2 首期范围内：

- 保存每轮完整对话副本；
- 把 Planner 的临时执行步骤永久保存为长期记忆；
- 让 LLM 自由生成身份、项目权限或任意 `memory_key`；
- 用长期记忆替代 TaskResult、会话历史或 Checkpoint；
- 在没有评测的情况下自动保存大量推测性信息。

## 2. 当前实现事实

### 2.1 已有能力

当前 `MemoryService` 已具备基础版能力：

- `MemoryItem(content, importance)`：无类型的事件文本；
- `ProfileUpdates`：技术栈、兴趣、经验和偏好；
- 事件写入 MySQL `user_memory`；
- 事件向量写入 ES `user_memories`；
- 用户画像写入 MySQL `user_profile`；
- ES KNN 使用 `user_id` 前置过滤；
- ES 返回候选 `memory_id`，再回 MySQL读取最新正文；
- 低访问记忆衰减，并同步删除 ES 文档；
- 显式画像信号触发提取，普通事件默认每 6 个用户轮次提取一次；
- 同一会话使用 Redis 做 300 秒提取节流。

当前 KNN 调用关系如下：

```text
main.py
  memory_service.recall(request.user_id, processed_message, top_k=3)
       ↓
MemoryService.recall()
       ↓
MemoryService._search_memories()
       ↓
AsyncElasticsearch.search(knn.filter=user_id)
```

其中：

```text
request.user_id   → ES term(user_id)
processed_message → query_vector
top_k=3           → k=3、size=3、num_candidates=9
```

### 2.2 当前缺口

| 缺口 | 当前表现 | V2 目标 |
|---|---|---|
| 事件类型 | 所有事件只有 `content` | `constraint / decision / goal` |
| 作用域 | 只有 `user_id` | `USER / PROJECT` + `project_id` |
| 生命周期 | 保留、衰减或物理删除 | active、superseded、completed 等状态 |
| 冲突处理 | 画像字典新值覆盖旧值 | canonical key + 替代链 + 来源审计 |
| 召回层次 | 图执行前一次 recall | 规划前召回 + Task 级召回 |
| 注入位置 | 插入 `history_messages` 的 system 消息 | 独立 `AgentState.memory_context` |
| MySQL复核 | 只按 `memory_id IN (...)` | 同时校验 user/scope/status/type/expiry |
| API接入 | 主要接入流式链路 | 所有 chat/resume 收口语义一致 |
| 数据迁移 | 仓库没有正式 migration | 显式 DDL、版本化索引、回灌和校验 |

另外，当前 `_find_last_user_text()` 正向遍历消息，实际取得第一条 user 消息；目标实现必须倒序查找最近一条用户消息。

## 3. 目标记忆模型

### 3.1 用户画像与事件必须分开

用户画像描述相对稳定的用户属性：

```json
{
  "tech_stack": ["Java", "Spring Boot", "LangGraph"],
  "experience": "mid",
  "preferences": {
    "response_language": "zh-CN",
    "code_language": "Java"
  }
}
```

事件记忆描述某个时间和作用域内已经确认的信息：

```text
constraint：以后代码示例默认使用 Java

decision：EasyJob 的 TaskResult 按 task_id 保存，而不是按 Subagent 保存

goal：后续实现 Main Agent 的阶段化调度
```

会话滚动摘要不是事件记忆。每 6 轮触发的是一次“提取”，输出应是 1～3 条原子化事实，而不是把六轮对话全文总结后直接长期保存。

### 3.2 事件类型

首版目标枚举：

| 类型 | 含义 | 示例 | 生命周期特点 |
|---|---|---|---|
| `constraint` | 后续行为必须遵守的稳定约束 | 默认使用 Java；文档放 docs | 同一 key 通常只允许一个 active 值 |
| `decision` | 用户已经确认的方案或已成功执行的结果 | TaskResult 按 task_id 保存 | 可保留版本和替代链 |
| `goal` | 跨轮持续但尚未结束的目标 | 以后实现阶段化调度 | 完成或取消后不再正常召回 |

`goal` 只保存持续目标，不保存 Planner 本轮生成的临时步骤。临时计划属于 AgentState/TaskResult，不能因为执行中间态不断变化就写入长期记忆。

### 3.3 目标逻辑字段

下面是目标逻辑模型，不是已经执行的 DDL：

| 字段 | 用途 |
|---|---|
| `memory_id` | 全局唯一 ID |
| `user_id` | 必填，用户隔离边界 |
| `memory_type` | constraint / decision / goal |
| `scope_type` | USER / PROJECT |
| `project_id` | PROJECT 作用域必填 |
| `memory_key` | 后端解析得到的稳定语义键 |
| `memory_value` | 可比较、可更新的规范化值，允许 JSON |
| `content` | 给模型阅读的完整陈述及必要上下文 |
| `status` | active / superseded / completed / cancelled / expired |
| `supersedes_memory_id` | 新记录替代的旧记录 |
| `source_conversation_id` | 来源会话 |
| `source_message_id` | 来源消息或确认点 |
| `source_type` | explicit_user / confirmed_result / extraction |
| `confidence` | 提取置信度，不代替确定性校验 |
| `importance` | 召回与遗忘权重 |
| `expires_at` | 可选过期时间 |
| `content_hash` | 幂等去重 |
| `create_time/update_time` | 审计时间 |

### 3.4 `memory_key`、`memory_value` 与 `content`

三者职责不能混淆：

```json
{
  "memory_type": "constraint",
  "memory_key": "default_code_language",
  "memory_value": "java",
  "content": "用户明确要求后续代码示例默认使用 Java"
}
```

- `memory_key`：用于定位“同一件事”，必须稳定。
- `memory_value`：用于机器比较、更新和冲突判断。
- `content`：用于向量化、召回后展示和注入模型。

LLM 可以提出候选类型和值，但不能自由决定最终 `memory_key`。目标流程：

```text
LLM 提取候选语义
  ↓
MemoryKeyResolver 做确定性归一化
  ├─ 命中受控 key 注册表 → 接受
  ├─ 能由明确业务对象构造 → 接受
  └─ 无法稳定映射 → 不写 active 记忆，进入待确认流程
```

典型受控 key：

```text
default_code_language
response_language
response_detail_level
project_architecture
rag_retrieval_strategy
task_result_storage_key
```

对于开放域 decision/goal，后续实现前必须确定稳定 topic key 生成规则。不能直接使用 LLM 每次生成的自由文本作为 key，否则“code_language”“default_language”“preferred_java”会被误认为三件事。

## 4. 作用域与身份边界

### 4.1 作用域语义

- `USER`：当前用户在所有项目中的全局偏好或约束。
- `PROJECT`：只在指定项目中有效的约束、决策和目标。

即使 `scope_type=USER`，记录也必须带 `user_id`；它表示“该用户全局”，不是系统全局。

当前项目请求可见集合：

```text
user_id = viewer_user_id
AND status = active
AND (
    scope_type = USER
    OR (scope_type = PROJECT AND project_id = current_project_id)
)
```

项目级约束只在该项目内覆盖同 key 的用户级约束，不应把用户级记录标记为全局 superseded。

### 4.2 身份来源

可信链路应为：

```text
JWT
→ Java UserContext
→ 服务间认证后的 Python 请求
→ AgentState.principal / viewer_user_id
```

禁止从以下位置取得权限身份：

- 用户自然语言；
- Query Rewrite 输出；
- Planner 输出；
- LLM Tool 参数中的自由 `user_id`；
- 未认证的 Python 公网请求体。

还必须校验 `conversation_id`、`project_id` 确实属于或授权给当前用户。

## 5. 提取、去重与冲突处理

### 5.1 提取时机

沿用 V1 已确认原则：

1. assistant 最终回复成功持久化后，才允许提取。
2. 停在 `interrupt` 时不提取；resume 真正完成后再提取。
3. 命中“记住、以后默认、我是、我使用”等显式信号时即时提取。
4. 普通事件默认每 6 个用户轮次批量提取一次。
5. 同一会话默认 300 秒节流。
6. 寒暄、确认、失败任务、工具原始结果、未确认建议不写长期记忆。

`6` 和 `300` 都必须配置化；它们是首期默认值，不是永久常量。

### 5.2 提取输入范围

不能每次反复扫描整段会话。目标实现增加提取水位：

```text
last_memory_extracted_message_id
```

本次只读取：

```text
(last_memory_extracted_message_id, current_final_message_id]
```

提取成功后事务性推进水位，并用：

```text
user_id + source_message_range + content_hash
```

保证重复任务不会重复写入。

### 5.3 冲突处理规则

#### 约束冲突

同一 `user_id + scope + memory_key` 的 active constraint 出现新值时：

```text
旧记录 status = superseded
新记录 status = active
新记录 supersedes_memory_id = 旧记录ID
```

例如：

```text
旧：default_code_language=java → superseded
新：default_code_language=python → active
```

#### 用户级与项目级冲突

项目级记录优先于用户级记录，但仅在当前项目生效：

```text
USER/default_code_language=java
PROJECT/easyjob/default_code_language=python
```

在 EasyJob 中使用 Python；其他项目仍使用 Java。两条都可以保持 active。

#### 决策更新

同一主题的方案被明确修改时建立替代链；历史决策保留用于审计，但正常召回只取最新 active 版本。

#### 目标更新

- 新建：`active`
- 完成：`completed`
- 用户取消：`cancelled`
- 被新目标替代：`superseded`
- 到期：`expired`

状态变化必须由确定性业务事件或明确用户确认触发，不能仅凭 LLM 推测。

#### 模糊冲突

无法判断是否为同一 key、用户表达不明确或来源相互矛盾时，不得直接覆盖 active 记忆。目标实现应创建候选审核记录或要求用户确认；首期也可以选择拒绝写入，但不能静默猜测。

## 6. 两级召回与 Agent 注入

### 6.1 规划前召回

Main Agent 生成计划前召回：

- 精简用户画像；
- 当前用户和项目的 active constraints；
- 与当前问题相关的关键 decisions；
- 与当前请求相关的 active goals。

流程：

```text
当前用户请求
  ↓
Recall Gate
  ↓
构造 MemoryQuery（后端补 user/scope）
  ↓
ES KNN 前置过滤
  ↓
MySQL 二次校验
  ↓
去重、冲突归并、Token Budget
  ↓
AgentState.memory_context.plan_context
  ↓
Main Agent 规划
```

画像不应编译进静态 System Prompt。它在数据库中会更新，应在请求时读取当前版本，并放入独立上下文字段。

### 6.2 Task 级召回

计划生成后，每个 Task 只召回自己需要的记忆：

```python
class MemoryRequirement(BaseModel):
    enabled: bool = False
    memory_types: list[str] = []
    scope: str = "project_and_user"
    top_k: int = 3

class PlannedTask(BaseModel):
    task_id: str
    subagent: SubagentName
    instruction: str
    depends_on: list[str]
    goal_refs: list[str] = []
    memory_requirement: MemoryRequirement
```

字段职责：

- `goal_refs`：当前 Task 服务于哪些已知持续目标，用于追踪和完成状态更新，不承载记忆正文。
- `memory_requirement`：声明允许召回哪些类型、范围和数量。
- `instruction`：作为任务级向量查询文本的一部分。

执行时：

```text
Task instruction + current request + goal_refs
  ↓
TaskMemoryRecall
  ↓
只取该 Task 允许的类型和 scope
  ↓
AgentState.current_task_memory
  ↓
注入对应 Subagent
```

禁止把所有长期记忆广播给所有 Worker。Search、Analysis、Writing、Chat 的记忆需求不同，Subagent 只能继承或收窄 Main Agent 的权限。

### 6.3 独立状态字段

目标状态至少区分：

```python
class AgentState(TypedDict):
    user_message: str
    history_messages: list[dict]       # 短期会话上下文
    memory_context: dict               # 规划前长期记忆
    current_task_memory: list[dict]    # 当前任务长期记忆
```

长期记忆可以在最终 Prompt 组装时渲染为 system section，但不应混进可持久化的普通对话消息，也不应再次被摘要器当作用户说过的新内容。

## 7. ES KNN 与 MySQL 事实源

### 7.1 目标 KNN 前置过滤

目标 ES mapping 需要增加：

```text
memory_type keyword
scope_type  keyword
project_id  long
status      keyword
expires_at  date
memory_key  keyword
```

查询示例：

```python
filter_clauses = [
    {"term": {"user_id": viewer_user_id}},
    {"term": {"status": "active"}},
    {"terms": {"memory_type": requested_types}},
    {
        "bool": {
            "should": [
                {"term": {"scope_type": "USER"}},
                {
                    "bool": {
                        "filter": [
                            {"term": {"scope_type": "PROJECT"}},
                            {"term": {"project_id": current_project_id}},
                        ]
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    },
    {
        "bool": {
            "should": [
                {"bool": {"must_not": [{"exists": {"field": "expires_at"}}]}},
                {"range": {"expires_at": {"gt": "now"}}},
            ],
            "minimum_should_match": 1,
        }
    },
]

response = await es.search(
    index="user_memories_v2",
    knn={
        "field": "content_vector",
        "query_vector": query_vector,
        "k": top_k,
        "num_candidates": max(top_k * 10, 50),
        "filter": {"bool": {"filter": filter_clauses}},
    },
    source=["memory_id"],
    size=top_k,
)
```

权限和生命周期条件必须放进 `knn.filter`，不能先全量召回再在 Python 中过滤。

### 7.2 MySQL 二次校验

ES 只返回候选 ID 和 score，随后 MySQL 使用同样边界复核：

```sql
SELECT memory_id, memory_type, scope_type, project_id,
       memory_key, memory_value, content, status,
       importance, expires_at
FROM user_memory
WHERE user_id = :userId
  AND memory_id IN (...)
  AND status = 'active'
  AND memory_type IN (...)
  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
  AND (
      scope_type = 'USER'
      OR (scope_type = 'PROJECT' AND project_id = :projectId)
  );
```

回查结果必须按照 ES 候选 ID 顺序恢复排名。当前 `IN (...)` 返回顺序不稳定，不能直接使用数据库行顺序。

MySQL 查询失败、身份缺失或 scope 无法验证时应 Fail-Closed：不向 Main Agent/Subagent 注入事件记忆。

### 7.3 用户画像读取

用户画像以 `user_id` 精确查询 MySQL，不需要每次做向量搜索。目标 Prompt 只注入压缩后的当前画像，并设置独立 Token Budget。

## 8. 一致性、安全与可观测性

### 8.1 数据一致性

- MySQL 是内容、状态、scope 和冲突关系的事实源。
- ES 是可重建的向量派生索引。
- 写 MySQL 成功、写 ES 失败时必须记录待同步事件，不能只打日志后永久丢失。
- 删除、过期、supersede 后要同步更新或删除 ES 文档。
- 建立周期性对账：MySQL active 集合与 ES 可召回集合一致。

后续优先考虑事务 Outbox，而不是依赖进程内 `asyncio.create_task()` 保证可靠投递。

### 8.2 安全规则

1. 所有查询必须包含可信 `user_id`。
2. PROJECT scope 必须校验项目成员关系。
3. Main Agent、Subagent、Tool 均不能扩大 scope。
4. 日志不得记录完整私密记忆正文；只记录 ID、类型、scope 和命中数量。
5. 用户删除账户、项目或记忆时，MySQL、ES、缓存和备份策略必须闭环。
6. 记忆内容是非可信输入，注入 Prompt 时要明确标记为“历史事实候选”，不能当成系统指令执行。

### 8.3 建议指标

```text
recall_requested_total
recall_hit_total
memory_candidates_es
memory_rows_mysql_validated
memory_cross_user_rejection_total
memory_conflict_total
memory_superseded_total
memory_extract_success/failure
memory_index_lag_seconds
memory_injection_tokens
```

## 9. 迁移方案

### 9.1 MySQL

1. 新增正式 migration，不依赖手工预建表。
2. 为 `user_memory` 增加 V2 字段或新建 V2 表。
3. 添加唯一性/查询索引，例如：

```text
(user_id, scope_type, project_id, memory_type, memory_key, status)
(user_id, status, update_time)
(source_conversation_id, source_message_id)
```

4. 旧无类型事件不能自动假定为 constraint/decision/goal。应根据来源重新提取或标记为 legacy，未经复核不能作为强约束注入。

### 9.2 Elasticsearch

使用版本化索引：

```text
user_memories_v2
alias: user_memories_read / user_memories_write
```

流程：

```text
创建新 mapping
→ 从 MySQL 回灌 active V2 记录
→ 校验 user/scope/status/向量维度
→ shadow recall 对比
→ 原子切换 alias
→ 保留旧索引回滚窗口
```

现有 `ensure_user_memories_index()` 遇到索引已存在就跳过，不能依靠修改常量完成 mapping 升级。

## 10. 分阶段实施顺序

### Phase 0：修正 V1 正确性

- 修复 `_find_last_user_text()` 倒序查找；
- 非流式 `initial_state` 补可信 `user_id`；
- MySQL 回查补 `user_id`；
- 按 ES ID 恢复排序；
- 四个 chat/resume 入口统一提取收口语义；
- 补正式数据库 migration。

### Phase 1：结构化 V2 存储

- 定稿枚举、字段和状态机；
- 实现 MemoryKeyRegistry/Resolver；
- 实现提取水位、幂等键和候选审核；
- 实现冲突替代事务；
- 建立 V2 ES mapping 和可靠索引事件。

### Phase 2：规划前召回

- 新增 `MemoryQuery`、`MemoryContext`；
- 请求入口构造可信 scope；
- ES 前置过滤 + MySQL 复核；
- 将结果放入独立 `AgentState.memory_context`；
- 建立 Token Budget 和审计日志。

### Phase 3：Task 级召回

- 扩展 `PlannedTask.goal_refs/memory_requirement`；
- 在 Subagent Runner 前执行精准召回；
- 按 Subagent 和 Task 裁剪类型、scope、数量；
- 对完成/取消的 goal 回写状态。

### Phase 4：治理与评测

- 冲突、过期和被遗忘权；
- ES/MySQL 对账；
- 提取质量与召回质量评测；
- 基于指标调整 6 轮、300 秒、top_k 和 Token Budget。

## 11. 验收标准

V2 实施完成至少满足：

- 用户 A 的查询无法在 ES 候选、MySQL 回查或 Prompt 中接触用户 B 的记忆；
- 项目 A 的记忆不会注入项目 B；
- 同 key 新约束生效时，旧约束可审计但不再正常召回；
- completed/cancelled/expired goal 不参与普通规划召回；
- Main Agent 能在规划前获得必要约束；
- 每个 Subagent 只获得当前 Task 允许的记忆；
- ES 脏数据不会绕过 MySQL 复核；
- interrupt 中间态和失败任务不会形成 active 决策；
- 长期记忆不会被重复写进短期历史或再次摘要；
- 所有索引和状态失败都有可观测、可重放路径。

## 12. 实施前必须确认的事项

以下内容仍需在编码前定稿，本文不把它们伪装成已确认实现：

1. V2 使用扩展 `user_memory` 还是新表。
2. status 和 source_type 的最终枚举名。
3. 开放域 decision/goal 的 canonical key 生成规则。
4. 模糊冲突采用候选表、pending 状态还是用户即时确认。
5. 用户画像是否继续 JSON 合并，还是升级为带来源和 last_seen 的事实表。
6. 规划前和 Task 级召回的 top_k、阈值、Rerank 与 Token Budget。
7. PROJECT scope 是否支持多人共享，以及成员变更后的可见性处理。
8. goal 完成状态由用户确认、业务事件还是 Main Agent 建议触发。
9. Outbox、重试、DLQ 和对账任务的具体实现。

## 13. 相关文档

- `docs/agent/memory/memory-trigger-strategy.md`：V1 触发策略。
- `docs/agent/memory/memory-trigger-implementation.md`：V1 接入设计与历史说明。
- `docs/agent/context/conversation-mysql-checkpoint.md`：短期上下文与摘要游标。
- `docs/learning/agent/21-main-agent-subagent-staged-architecture.md`：Main Agent、Task 与 Subagent 目标架构。
- `docs/archive/java-agent/10-context-management.md`：更早期 Java 上下文方案，不作为当前 Python 实现依据。
