# EasyJob AI Agent：从当前代码到目标架构的统一实施路线

> 文档状态：**统一实施路线，尚未按本文完成改造**  
> 创建日期：2026-08-21  
> 最近修订：2026-10-01（补充当前任务合同与服务端能力边界）  
> 适用范围：EasyJob Java 后端、Python Agent、Elasticsearch、MySQL、Redis、RabbitMQ 与 AI Chat 前端  
> 历史运行基线：扁平 `Planner → 并行 Worker → Reflector → Synthesizer`；当前入口为主 Agent 直接执行、子代理按需委派，部署验收待完成（见第18节）  
> 目标运行基线：可信 Principal 驱动的阶段化 Main Agent、受限 Subagent、可验证 RAG、长期记忆 V2、结构化运行轨迹与评测闭环

> 当前实现说明：Main 使用动态 `answer/retrieve/delegate/write_draft` 动作循环；`subagent` 只在委派待执行任务中选择 Search/Analysis，草稿请求是 `draft_request`，内部执行任务及新结果分别记录 `kind` 与 `actor`，权限由服务端能力政策计算。当前合同、历史内部格式兼容和审批边界见 [任务、执行者与能力边界](22-task-execution-boundaries.md)，运行范围见 [`python-agent/STAGED_SETUP.md`](../../archive/setup/STAGED_SETUP.md)。除第18节当前状态说明外，正文的旧类名、扁平图基线、阶段 Barrier 和角色授权等属于历史设计或未完成目标，不能当作现有代码合同。

本文是从当前代码演进到目标代码的**唯一统一执行入口**，用于回答：先改什么、后改什么、每一步涉及哪些文件、完成到什么程度才允许进入下一阶段。

本文不替代以下详细设计：

- [`19-hitl-draft-persistence.md`](19-hitl-draft-persistence.md)：草稿确认、消息引用和前端交互的历史设计；其中 Python 直写文章表、Markdown 草稿等内容以本文修订为准。
- [`20-rag-optimization.md`](20-rag-optimization.md)：Query Rewrite、Filter、RRF、Citation 总路线；其中早期 Parent Chunk 方案以文档 23 为准。
- [`21-main-agent-subagent-staged-architecture.md`](21-main-agent-subagent-staged-architecture.md)：Task、DAG、Stage、Barrier、权限、EvidencePool 与重规划详细设计。
- [`22-long-term-memory-v2.md`](../../agent/memory/22-long-term-memory-v2.md)：长期记忆 V2 数据模型、两级召回和治理方案。
- [`23-structured-article-chunking.md`](23-structured-article-chunking.md)：结构化分片、版本索引和同粒度检索详细设计。

---

## 1. 实施原则

### 1.1 不能按文档编号机械执行

当前仓库是混合状态：

- 19、20 的部分代码已经提前写入，但存在阻断性缺陷；
- 21、22、23 主要是目标设计，尚未进入真实运行链路；
- 旧扁平 LangGraph 仍是生产入口；
- RAG、HITL、Memory、SSE 的不同入口语义不完全一致。

因此必须按技术依赖执行：

```text
建立最小回归集并修复当前正确性
→ 建立可信身份与统一运行入口
→ 跑通固定依赖链和HITL边界（首轮交付）
→ 按真实需求扩展动态DAG，完善运行轨迹与评测
→ 重建可靠索引和目标RAG
→ 增加EvidenceGate与增量重规划
→ 升级Memory V2
→ 最后做缓存、自纠错和持续进化
```

### 1.2 模型与确定性代码的职责边界

模型负责：

- 理解用户意图；
- 拆解语义任务；
- 生成查询候选；
- 基于已授权证据分析和生成内容；
- 提出质量判断或改进建议。

确定性代码负责：

- 身份和权限；
- Schema 校验、Task 唯一性、依赖校验和环检测；
- Kahn 拓扑分层；
- Stage Barrier 完整性检查；
- Tool 白名单与参数权限；
- 预算、超时、幂等、事务和状态机；
- 引用存在性、文档可见性和业务状态复核；
- 数据迁移、索引版本、审计和回滚。

### 1.3 必需链路 Fail-Fast，可选能力允许受控降级

失败策略由确定性代码按任务契约决定，不由模型临时判断。权限失败、契约错误和必需依赖失败必须停止对应链路；可选能力失败可以降级，但不能扩大权限或伪造成功。

| 情况 | 首版处理 |
|---|---|
| 身份、ACL、Schema、引用装配或必需依赖错误 | 明确失败，禁止继续消费不可信结果 |
| 核心检索不可用或没有足够证据 | 明确说明无法完成当前检索目标，不凭常识补成有据回答 |
| 可选联网补充失败 | 已授权的平台证据足够时继续，标记外部补充未完成；必须依赖实时信息的任务仍失败 |
| 可选画像/记忆服务不可用 | 不注入记忆，继续当前任务；若任务明确要求历史记忆则说明无法满足 |
| Reranker 超时 | 仅在契约和回归允许时沿用已授权的融合排序，记录 `degraded` 和原因 |

降级结果至少携带 `status/reason/available_evidence_ids`，下游明确声明可容忍才允许使用。授权复核失败的候选必须丢弃，不能套用上述降级策略。

以下行为禁止继续保留或新增：

- RAG 契约错误后静默退回模型常识；
- 权限条件缺失时退化为全量检索；
- 必需依赖任务失败后仍让 Analysis/Writing 继续生成；
- Tool 执行异常后把自然语言错误消息当作成功结果；
- 解析或分片失败后把整篇原始 HTML 当成一个 Chunk；
- ES 写入失败只打日志、不建立可重放事件；
- 更新索引时先删除旧版本，再尝试构建新版本；
- HITL resume 重放草稿生成并覆盖用户已预览内容。

### 1.4 每个阶段必须有门禁

一个阶段只有同时满足以下条件才能进入下一阶段：

1. 代码契约完成；
2. 数据迁移和兼容策略完成；
3. 权限与失败路径完成；
4. 对应验证资产和指标完成；
5. 灰度、回滚或旧路径保留策略明确；
6. 文档中的“已实现”状态与真实代码一致。

### 1.5 首轮交付范围与后续立项边界

首轮只交付 Phase 0、Phase 1 和 Phase 2A：阻断修复、可信身份与会话授权、最小回归集、固定检索到写作链路、草稿审批与幂等保存。普通 Chat 和单 Search 保留直接路径。

首轮不以动态 DAG、跨轮证据池、Memory V2 或自动重规划完成为验收前提。Phase 2B 在多实例任务或复杂依赖有真实用例时立项；Phase 4～7 按检索质量、故障记录和成本收益决定投入。若索引故障已阻断首轮验收，先修复相应正确性问题，不等待完整 Phase 4。

Phase 3 在首轮后完善观测和评测；后续任一优化发布前必须已有对应 baseline。保留长期目标，但不能把全部长期目标当作首轮上线条件。

---

## 2. 改造起点代码基线（历史快照，当前实现见第18节）

### 2.1 Agent 编排

当前真实图位于：

- `python-agent/app/graph/builder.py`
- `python-agent/app/graph/state.py`
- `python-agent/app/graph/nodes/planner.py`
- `python-agent/app/graph/nodes/dispatcher.py`

当前流程：

```text
START
  ↓
Planner：active_workers + task_descriptions
  ↓
Dispatcher：Send多个Worker到同一superstep
  ├─ SearchWorker
  ├─ AnalysisWorker
  ├─ WritingWorker
  └─ ChatWorker
  ↓
Reflector
  ├─ needs_retry → Planner
  └─ pass → Synthesizer
  ↓
END
```

已具备：

- Planner 结构化输出；
- LangGraph `Send` 并行 Worker；
- Redis Checkpointer；
- 基础 Reflector；
- Synthesizer；
- SSE 基础进度；
- Writing interrupt/resume 雏形。

核心缺陷：

- Search、Analysis、Writing 被放在同一 superstep 时，后两者读不到前者新结果；
- 一个 Worker 一轮只能对应一个扁平任务，缺少 `task_id`；
- 没有 `depends_on`、DAG、Stage 和 Barrier；
- `worker_results: list + add` 无法表达依赖和结果版本；
- Reflector 失败后回 Planner，但 Planner 输入变化不足，可能重复原计划；
- 当前异常路径可能把失败转成可继续消费的自然语言结果。

### 2.2 身份、权限与 Tool

当前文件：

- `python-agent/app/main.py`
- `python-agent/app/services/tool_registry.py`
- `python-agent/app/graph/tool_executor.py`
- 各 Worker 节点。

已具备：

- 本地 Tool 和 MCP Tool 注册；
- `tool_registry.get_tools(names)`；
- Tool 总超时、结果长度限制和基础参数检查。

核心缺陷：

- Python 入口直接采信请求体 `user_id`；
- `conversation_id`、Checkpoint resume、cancel 缺少统一所有权校验；
- Search/Analysis/Writing 仍调用 `get_all_tools()`；
- Tool 白名单没有成为强制能力边界；
- 没有可信 `Principal`、资源级授权和风险分级；
- Tool 参数校验主要只覆盖 `web_search.query` 长度；
- 缺少 Task 级调用预算、幂等键和结构化失败结果。

### 2.3 RAG

当前目标链路已出现于：

- `python-agent/app/services/query_rewrite.py`
- `python-agent/app/services/filter_resolver.py`
- `python-agent/app/services/retrieval_service.py`
- `python-agent/app/services/reranker.py`
- `python-agent/app/graph/nodes/search_worker.py`
- `python-agent/app/clients/es_client.py`

当前阻断问题：

1. `QueryRewriteService.rewrite()` 返回 dict 时缺少 `filters/search_mode/need_web_search`；
2. `search_worker.py` 读取 `rewrite_result["filters"]`，可能直接抛错；
3. `RetrievalService` 调用的方法名与实际定义不一致；
4. `EsVectorStore.search()`、`EsComponent.search()` 尚未完整接收 filter；
5. `citation_builder_instance` 未定义或未正确装配；
6. 普通流和 resume 流没有统一下发 Citation；
7. Search Worker 前置 RAG 后仍暴露裸站内搜索 Tool，形成双检索入口；
8. ES 召回没有可信 Principal ACL；
9. MySQL 卡片/引用回查没有完整复核发布状态、删除状态和查看权限。

### 2.4 文章分片与索引

当前 Java 链路：

```text
ArticleServiceImpl
→ RabbitMQ PUBLISH/UPDATE
→ ArticleVectorListener
→ DocumentChunkService
→ EsVectorStore
→ article_vectors
```

当前文件：

- `src/main/java/com/easyjob/agent/component/DocumentChunkService.java`
- `src/main/java/com/easyjob/listener/ArticleVectorListener.java`
- `src/main/java/com/easyjob/agent/component/EsVectorStore.java`
- `src/main/java/com/easyjob/entity/DocumentChunk.java`
- `src/main/java/com/easyjob/dto/ArticleVectorMessage.java`

已具备：

- 发布/更新消息驱动；
- HTML 转纯文本；
- TokenTextSplitter；
- Embedding；
- ES bulk 写入框架。

核心缺陷：

- `Jsoup.text()` 丢失标题、段落、代码、表格和列表结构；
- 固定 500 token，配置未真正绑定；
- YAML 中 overlap 不代表实际生效；
- 最多 50 块但缺少完整性校验；
- Embedding 逐块调用；
- bulk 未完整检查 item 级失败；
- UPDATE 先删旧块，失败会产生索引空窗；
- PUBLISH 可能残留旧尾块；
- 缺少 `article_version/source_hash/parser_version/chunker_version`；
- 缺少版本索引、alias、Outbox、DLQ 和对账。

### 2.5 HITL 草稿

当前文件：

- `python-agent/app/graph/nodes/writing_worker.py`
- `python-agent/app/services/save_draft_to_article_info.py`
- `python-agent/app/graph/nodes/synthesizer.py`
- `python-agent/app/services/conversation.py`
- `python-agent/app/main.py`
- `frontend/src/views/AiChat.vue`

已具备草稿结构化输出、interrupt/resume、草稿 ID 和前端入口的部分代码。

当前阻断问题：

- `DraftOutput` 与保存服务存在循环导入风险；
- 非流式入口缺少完整 `user_id/state`；
- 四个 chat/resume 入口的消息持久化字段不一致；
- 草稿生成、Approval 和保存副作用在同一节点，resume 可能重放生成；
- Python 直接写 Java 所拥有的 `article_info` 表，跨越服务边界；
- 当前真实创作和展示主链是 HTML，而旧方案按 Markdown 保存草稿；
- `draft_article_id` 的正式 migration 未形成可确认的仓库资产。

### 2.6 短期上下文与长期记忆

当前已具备：

- 会话滚动摘要、摘要游标、Redis 缓存；
- Memory V1 的用户画像和无类型事件；
- MySQL `user_memory/user_profile`；
- ES `user_memories`；
- ES KNN 的 `user_id` 前置过滤；
- 每 6 用户轮次、300 秒节流等触发雏形。

当前缺陷：

- `_find_last_user_text()` 正向遍历，取到第一条而不是最后一条用户消息；
- MySQL 回查未再次按可信 `user_id` 复核；
- 回查结果未按 ES 候选顺序恢复；
- Memory 主要接入流式入口；
- 记忆被混入 `history_messages`，可能再次被摘要；
- 提取使用进程内 `asyncio.create_task()`，无可靠投递；
- 无提取水位、幂等键、类型、scope、状态和替代链；
- 无规划前召回与 Task 级召回。

### 2.7 评测、轨迹和可观测性

已具备：

- Redis Checkpoint；
- 基础日志；
- Langfuse callback/decorator；
- Tool 调用耗时和返回摘要；
- SSE 粗粒度进度。

核心缺陷：

- Redis Checkpoint 不是长期业务审计；
- 缺少 `request_id/plan_attempt/task_id/evidence_id/tool_call_id` 统一链路；
- 缺少离线 Agent/RAG/Memory 数据集；
- 缺少可重复评测 runner 和发布门禁；
- `CostTracker` 仅定义，未进入真实调用链；
- Reflector 自评分不能替代确定性验证器；
- 缺少失败轨迹的首错归因。

---

## 3. 目标架构

```text
可信请求入口
  ↓
RunService
  ├─ Principal与资源所有权校验
  ├─ 会话上下文
  ├─ 规划前Memory召回
  ├─ ExecutionBudget
  └─ request_id/trace_id
  ↓
Main Agent（本次调用直接分析并选择下一步；可同时输出已完成产物artifacts）
  ├─ answer → 最终校验与交付
  ├─ retrieve → 共享RAG取证 → 结果/状态回到Main
  ├─ delegate（独立并行工作或上下文隔离有收益时）
  │    → DAG参数/依赖校验 → 依赖就绪调度Search/Analysis
  │    → 成功结果与失败状态回到Main
  └─ write_draft → 固定生成/来源校验/审批/修改/保存流程
       → 保存或放弃后确定性交付，不再由模型选择动作
  ↓
最终引用/来源校验 → 运行结果提交 → 回答 + Citation + Cards + Draft Reference
```

本节及第18.1节是当前编排规则。后文 StageDispatcher/Barrier、顶层 workflow 和全局增量 replan 的早期设计须按“逐轮动作 + 依赖就绪执行 + 分层纠错”解释，不再作为当前入口实现或升级兼容承诺。Workflow 表示代码固定的业务边界，与是否委派正交。

目标 Harness：

```text
Context
  = 短期历史 + 规划前记忆 + Task级记忆 + 声明依赖 + Evidence

Tools
  = Subagent白名单 + 参数Schema + 资源授权 + 审计

Constrain
  = Principal + ACL + Budget + HITL + 幂等 + Fail-Closed

Verify
  = PlanValidator + Barrier + EvidenceGate + Citation校验 + 业务验证器

Correct
  = retry_stage + regenerate + incremental replan + 人工审批 + 可回滚版本
```

---

## 4. 必须先锁定的架构决策

以下决策作为后续代码统一口径：

1. **当前文章规范格式为 HTML。** wangEditor 输出继续作为事实源；真正 raw Markdown 编辑/导入/导出另立产品需求。
2. **Java 文章服务拥有 `article_info` 写权限。** Python 不再直接跨库写文章表。
3. **草稿保存不是 LLM Tool。** Approval 通过后，由确定性 `SaveDraftNode → DraftGateway → Java 内部 API` 执行。
4. **依赖顺序由确定性代码控制。** Phase 2A 使用固定工作流；Phase 2B 的动态 Planner 只输出 Task 与 `depends_on`，Stage 由后端 Kahn 算法生成。
5. **共享检索服务是 RAG 唯一管线。** Main Agent 与 Search Subagent 调用相同的改写、召回、授权复核、重排及引用构建；不提供旁路裸搜索。普通聊天直接回答，单次查询直接调用服务，子代理按收益委派；不强制每次规划或增加额外 LLM 分类器。
6. **Principal 只来自可信服务端。** 用户自然语言、Planner、Query Rewrite 和 Tool 参数均不能生成或提升身份。
7. **Subagent 权限只能继承或收窄。** 不允许创建比 Main Agent 更大的资源范围或 Tool 集合。
8. **MySQL 是业务事实源，ES 是可重建派生索引。** ES 候选必须通过 MySQL 最新状态和授权复核。
9. **运行时 Context 与不可变轨迹分离。** Context 可以压缩和裁剪，审计轨迹按保留策略追加记录。
10. **评测先于编排切换和高级优化。** Phase 0 建立最小回归集，Phase 3 扩展完整评测；每次切换必须留下对照结果。
11. **首版同会话只允许一个非终态运行。** chat、resume、cancel 通过同一运行状态机协调，审批绑定具体运行和草稿版本。

尚需用户在对应阶段编码前确认的事项集中列在第 15 节。

---

## 5. 总体依赖关系

```text
Phase 0 最小回归集 + 当前阻断修复
  ↓
Phase 1 可信运行入口与最小权限
  ↓
Phase 2A 固定依赖链 + HITL + 最小进度（首轮交付终点）
  ↓
Phase 3 完善轨迹与评测
  ↓
Phase 4 可靠索引 + 结构化分片 + 目标RAG/Citation
  ↓
Phase 5 EvidenceGate + 增量重规划
  ↓
Phase 6 Memory V2
  ↓
Phase 7 稳定性、性能、治理与离线持续进化
```

并行关系：

- Phase 2B 动态 DAG 是 Phase 2A 后的条件分支，可与 Phase 3 并行；Phase 4 的索引/RAG 不必等待 Phase 2B，但 Phase 5 的动态增量重规划必须等待 Phase 2B。
- Phase 0 的最小回归集先运行并记录已知失败，修复后复跑；Phase 3 完整评测框架可以与 Phase 4 的索引底座并行，但 Phase 4 切换前必须已有对应 baseline。
- Phase 6 的结构化存储可提前设计，但动态 Task 级召回必须等待 Phase 2B 的 `PlannedTask`、`Principal` 和 `SubagentRunner`。
- 前端最小进度可以与 Phase 2A 同步，完整 Stage 状态栏随 Phase 2B 接入。

禁止倒置：

- 不允许在 Principal 和 ACL 前上线跨用户 Memory V2；
- 不允许在最小回归集前切换编排；
- 不允许在 baseline 前切换结构化分片参数；
- 不允许在 TaskResult/Evidence 完成前实现自动 replan；
- 不允许在审批、幂等和服务边界完成前开放草稿保存；
- 不允许在检索入口唯一化前增加更多 Search Tool。

---

# Phase 0：收口现状并修复阻断问题

## 6. 阶段目标

让当前扁平架构至少满足：模块可装配、四入口语义一致、RAG 主链不因静态契约错误中断、Memory V1 不跨用户、HITL 不循环导入，并为后续迁移建立明确基线。

## 6.1 RAG 契约修复

- [ ] `QueryRewriteService.rewrite()` 返回完整 `RewriteResult`：
  - `semantic_queries`
  - `keywords`
  - `filters`
  - `search_mode`
  - `need_web_search`
- [ ] 统一 `RetrievalService` 方法命名，删除调用方和定义方不一致。
- [ ] `EsVectorStore.search()` 和 `EsComponent.search()` 明确接收可选 filter，并下推 ES。
- [ ] 新建并装配 `CitationBuilder`，禁止使用未定义全局变量。
- [ ] 明确无结果、超时、字段缺失、Reranker失败的结构化状态。
- [ ] 暂时保留手写双索引 RRF，但标记为迁移兼容层，不作为最终架构。

涉及文件：

- `python-agent/app/services/query_rewrite.py`
- `python-agent/app/services/retrieval_service.py`
- `python-agent/app/clients/es_client.py`
- `python-agent/app/graph/nodes/search_worker.py`
- 新增 `python-agent/app/services/citation_builder.py`

## 6.2 HITL 当前缺陷修复

- [ ] 消除 `DraftOutput` 与保存服务的循环导入：把 DTO 移到独立模型文件。
- [ ] 所有入口初始化完整 State。
- [ ] 普通流和 resume 流统一保存 `draft_article_id/article_cards/citations`。
- [ ] interrupt 控制流异常必须继续抛给 LangGraph，不能被普通异常捕获。
- [ ] 在 Phase 2 重构完成前，当前保存路径必须增加明确幂等保护或关闭重复提交入口。

建议新增：

- `python-agent/app/models/draft.py`

待 Phase 2 退役或重构：

- `python-agent/app/services/save_draft_to_article_info.py`

## 6.3 Memory V1 正确性修复

- [ ] `_find_last_user_text()` 改为倒序查找。
- [ ] MySQL 回查必须同时携带可信 `user_id`。
- [ ] 按 ES 返回的 `memory_id` 顺序恢复结果。
- [ ] 身份缺失或 MySQL 复核失败时 Fail-Closed，不注入事件记忆。
- [ ] interrupt、失败任务、未完成回复不触发记忆提取。

涉及文件：

- `python-agent/app/services/memory.py`
- `python-agent/app/main.py`

## 6.4 State 与入口一致性

- [ ] 盘点 `/chat`、`/chat/stream`、`/chat/resume`、`/chat/resume/stream` 的 State 字段。
- [ ] 使用同一工厂构造初始 State。
- [ ] 同一方法负责最终 State 读取、消息持久化和附属字段保存。
- [ ] Planner 降级分支补齐结构化输出字段；长期目标是移除静默关键词降级。
- [ ] 同一入口语义下统一取消、超时、interrupt 和最终完成判定。
- [ ] 修复 Java `AgentService.chat()` 用 `Map.of()` 传入可空 `conversationId` 的问题：使用允许 null 的请求 DTO/Map，明确 null 表示创建新会话。
- [ ] Java 新会话请求必须实际到达 Python；非流式和流式创建会话均纳入回归。

建议新增：

- `python-agent/app/services/run_service.py`
- `python-agent/app/graph/state_factory.py`

涉及现有文件还包括 `src/main/java/com/easyjob/agent/service/AgentService.java`。

## 6.5 数据库迁移基线

- [ ] 确认项目正式使用的 migration 工具和目录。
- [ ] 把 `ai_message.draft_article_id` 等已被代码依赖的字段纳入正式 migration。
- [ ] 建立 migration 版本、执行顺序、回滚说明和部署检查。
- [ ] 禁止继续以“环境里已手工建表”为代码前置条件。

路径占位：

```text
<待确认的正式migration目录>/<version>__agent_baseline.sql
```

## 6.6 最小回归集与修复前后对照

- [ ] 在 `test/eval/agent_baseline/` 保存用例、预期业务行为、运行方式和报告；Phase 0 即建立，不等待完整评测平台。
- [ ] 覆盖普通 Chat、单 Search、Search→Analysis→Writing、四个 chat/resume 入口和新会话创建。
- [ ] 覆盖跨用户读历史/删除会话/resume/cancel、审批拒绝、重复 approve、超时及取消后的迟到结果。
- [ ] 覆盖向量生成失败、bulk 部分失败、旧事件晚到和文章删除；尚未修复的索引行为明确登记并禁用受影响路径，不能计为通过。
- [ ] 契约、授权、幂等和失败路径使用受控依赖及故障注入；少量真实模型/检索集成用例另跑，记录模型、Prompt、索引版本。
- [ ] 修复前记录已知失败，修复后保存同一组用例的对照；未完成阶段的用例标明阶段与状态，发布所覆盖路径不得保留未解释失败。
- [ ] Phase 2A 切换时复用这组用例，确认下游实际收到上游结果，以及保存内容与用户预览一致。

## 6.7 Phase 0 验收门禁

- [ ] Python Agent 模块完整导入时不存在循环导入。
- [ ] 四个 chat/resume 入口构造的核心 State 字段一致。
- [ ] Java 非流式新会话不因 null 参数抛错。
- [ ] RAG 不再因缺少 `filters`、方法名不一致、Citation未定义而失败。
- [ ] 用户 A 的 Memory 候选不能通过 MySQL 回查进入用户 B 的 Context。
- [ ] approve 同一操作最多保存一次；reject 不落库。
- [ ] 所有失败都以结构化错误暴露，不伪装为成功回答。
- [ ] 最小回归资产可重复运行；当前修复范围通过，后续阶段缺陷有明确登记和隔离策略。

---

# Phase 1：可信运行入口、Principal 与最小权限

## 7. 阶段目标

建立后续 Stage、RAG、Memory、Tool 和 HITL 共同依赖的可信控制边界。

## 7.1 统一 RunService

- [ ] 四个入口只负责协议适配，统一调用 `RunService`。
- [ ] `RunService` 负责：
  - 构造可信 Principal；
  - 校验会话所有权；
  - 生成 `request_id/trace_id`；
  - 获取短期上下文；
  - 初始化 ExecutionBudget；
  - 调用图；
  - 统一处理中断、恢复和取消；
  - 持久化最终消息及 Cards/Citations/Draft ID；
  - 成功后触发可靠的后处理事件。
- [ ] resume 和 cancel 必须校验 Checkpoint 对应的 conversation/request 所有权。
- [ ] 请求体 `user_id` 只能用于与可信身份做一致性校验，不能作为授权来源。

### 7.1.1 同会话并发与运行状态机

- [ ] 分离 `conversation_id`、`request_id` 和 `run_id`：会话承载历史，请求用于去重，运行标识一次执行及其恢复；resume/cancel 必须指向具体 run。
- [ ] 每个会话最多一个非终态 run，包含 `awaiting_approval`。新请求在已有运行时明确返回冲突；同一请求幂等键重试返回已有 run，不能重复追加用户消息。
- [ ] 多进程之间使用持久状态和原子竞争机制，不能仅使用进程内锁。租约续期、过期接管及单调递增的执行代次必须阻止旧执行者提交。
- [ ] 状态至少区分 `running/awaiting_approval/completed/failed/cancelled/expired`；转换使用比较并更新，终态不能被迟到结果覆盖。
- [ ] checkpoint 与 run 显式关联。审批等待期间保留会话运行占用，恢复时重新校验身份、run 状态与执行代次；不得只凭 `conv_{conversation_id}` 恢复当前未知运行。
- [ ] cancel 与完成/保存通过同一原子状态规则裁决。取消先被接受时，后续 TaskResult、消息提交和草稿保存不得继续；保存已提交时返回已保存事实，取消不暗示撤销。
- [ ] Java 草稿保存边界必须参与上述裁决，防止 Python 检查后、Java 提交前发生取消的竞态；只在 Python 提交前读一次 cancelled 不算实现。
- [ ] 用户审批携带 `run_id/approval_id/draft_version/content_hash`，绑定已预览内容；重复同决策返回已有结果，冲突或过期决策拒绝。修改草稿形成新版本并重新审批。
- [ ] 检查点/审批所需预算与权限在恢复时重新验证；等待审批不长期持有数据库事务或进程锁。

具体锁、租约和事务载体在实现前明确，但这些运行语义作为首版验收条件。

## 7.2 Principal 模型

建议模型至少包括：

```text
user_id
role
project_id
visible_scopes
conversation_id
request_id
```

- [ ] `Principal` 使用只读模型。
- [ ] Java 网关到 Python 使用服务间认证。
- [ ] Python 不接受未认证公网请求直接构造高权限 Principal。
- [ ] 项目、会话、文章、草稿等资源通过集中授权服务判断。

建议新增：

- `python-agent/app/security/principal.py`
- `python-agent/app/security/authorization_service.py`
- `python-agent/app/security/request_identity.py`

## 7.3 Tool 最小权限

- [ ] 建立 `SubagentSpec(handler, allowed_tools, allowed_resource_scopes)`。
- [ ] Worker 只调用 `tool_registry.get_tools(allowed_tools)`。
- [ ] 未注册 Tool、未知 Tool 或不在白名单中的调用直接拒绝。
- [ ] Tool 执行前再次调用 AuthorizationService 做资源授权。
- [ ] Tool 参数中的 `user_id/project_id` 不能覆盖 Principal。
- [ ] Tool 调用记录 `request_id/task_id/tool_call_id/principal/risk/result_status/duration`。
- [ ] 有副作用 Tool 增加幂等键和 HITL 风险分类。

首版权限边界：

```text
允许执行
= Principal资源权限
∩ Subagent工具白名单
∩ 当前Task授权
∩ 风险审批结果
```

## 7.4 RAG ACL

- [ ] ACL 条件编译进 KNN/BM25 的 ES filter。
- [ ] 权限 filter 永远非空；缺失 Principal 时查询零结果。
- [ ] 索引冗余 `status/is_deleted/visibility/user_id` 等权限字段。
- [ ] MySQL 卡片和 Citation 回查再次复核最新状态和权限。
- [ ] 审计日志只保存 filter 摘要和命中 ID，不记录不必要的私密正文。

## 7.5 Phase 1 验收门禁

- [ ] 自然语言“我是管理员”不能改变 Principal。
- [ ] Planner、Subagent 和 Tool 都不能扩大 scope。
- [ ] 用户 A 不能 resume/cancel 用户 B 的运行。
- [ ] Search/Analysis/Writing 不再获得全量 Tool。
- [ ] 无权限文章不进入 ES 候选、Python内存、日志、Citation或前端卡片。
- [ ] AuthorizationService 不可用时敏感操作 Fail-Closed。
- [ ] 会话历史读取和删除同样验证归属，不能只保护 chat/resume/cancel。
- [ ] 双击发送、跨实例同时请求、重复恢复和 cancel/完成竞态均有回归；同会话不能产生两个活跃运行。
- [ ] 过期执行者和取消后的迟到结果不能提交副作用。

---

# Phase 2：阶段化 Main Agent、Task Context、HITL 与状态栏

## 8. 阶段目标

将扁平 Worker 图迁移成依赖感知的 Main Agent 控制面，使 Search → Analysis → Writing 的结果真正按依赖传递。按 2A、2B 独立验收与切换，2B 不是首轮交付前提。

### 8.0.1 Phase 2A：固定依赖链与草稿闭环

- [ ] 路由仅在普通 Chat、单 Search、固定 Search→Analysis→Writing 工作流中选择；根据用例允许省略不需要的步骤，禁止并行执行存在依赖的步骤。
- [ ] 定义最小 `TaskResult(task_id, run_id, status, content, evidence_ids, error)`，后端分配 Task ID，向下游显式注入上游成功结果和对应证据。
- [ ] Analysis/Writing 不重复自行执行裸站内搜索；必需证据不足时明确停止或返回不足，不自行补齐事实。
- [ ] 先交付第 8.6 节草稿三节点、Java 保存边界和审批版本绑定，以及第 8.7 节最小结构化运行/任务/审批事件。
- [ ] 使用 Feature Flag 保留旧路径，复跑 Phase 0 回归和同会话并发用例；正常创建、恢复、拒绝、重复确认与取消均可复现。

2A 验收：检索结果实际进入分析和写作；必需步骤失败不启动下游；审批前后内容一致；一次审批最多保存一篇草稿；普通 Chat 和单 Search 无业务回归。

### 8.0.2 Phase 2B：按需求扩展动态 DAG

出现需要多个 Search 实例、分支汇合或动态依赖的已记录用例，并且固定工作流无法合理覆盖时，再实施第 8.1～8.5 节的完整 Task/DAG/Stage/Barrier/ContextBuilder。首版限制任务数与并发数，不同时引入自由 Agent 通信和自动重规划。

第 8.8 节切换和第 8.9 节验收分别记录 2A、2B 状态。Phase 2B 必须保留 2A 的业务回归结果，后续跨轮复用和增量 replan 属于 Phase 5。

## 8.1 Task、Plan 与拓扑分层

新增：

- `python-agent/app/graph/staged_plan.py`
- `python-agent/app/graph/staged_state.py`
- `python-agent/app/graph/nodes/staged_planner.py`

- [ ] 定义 `PlannedTask(task_id, subagent, instruction, depends_on)`。
- [ ] 定义 `DependencyPlan` 和任务数量上限。
- [ ] Planner 不直接输出 Stage。
- [ ] 后端校验：
  - Task ID 唯一；
  - 依赖存在；
  - 无重复依赖；
  - 禁止自依赖；
  - Subagent 在白名单；
  - instruction 长度和任务总量受限；
  - 副作用任务不能非法并行。
- [ ] 使用 Kahn 算法按层生成 Stage。
- [ ] 处理数量小于总任务数时明确报环。

## 8.2 TaskResult 与状态模型

- [ ] 用 `task_id -> TaskResult` 替代并行 Worker 直接追加 `worker_results`。
- [ ] TaskResult 至少包含：
  - request_id；
  - plan_attempt；
  - task_id；
  - stage_id/stage_index；
  - subagent；
  - status；
  - content；
  - evidence_ids/citations；
  - retrieved_count；
  - error；
  - started_at/completed_at；
  - token/tool/cost摘要。
- [ ] reducer 按 `run_id + plan_attempt + task_id + execution_generation` 合并：同一有效执行的完全相同重放幂等，冲突内容拒绝；旧执行代次及已终态运行的迟到结果丢弃并记录。
- [ ] 当前轮结果和历史 plan attempt 归档分离。

## 8.3 StageDispatcher 与 StageBarrier

新增：

- `python-agent/app/graph/nodes/stage_executor.py`
- `python-agent/app/graph/staged_builder.py`

- [ ] Dispatcher 只分发当前 Stage。
- [ ] 同 Stage Task 使用多个 `Send(subagent_runner, branch_state)` 并行。
- [ ] 每个 branch 只携带当前 Task 所需上下文。
- [ ] Barrier 检查预期 Task 是否全部返回。
- [ ] 必需 Task 失败时不推进下一 Stage。
- [ ] 必需任务失败遵循第 1.3 节 Fail-Fast；可选组件仅按已声明、已回归验证的策略降级。动态 `retry_stage/replan` 后置，不影响首版受控降级。
- [ ] 全 Stage 完成后由单一 `prepare_results` 节点生成兼容输出。

## 8.4 Task 级 ContextBuilder

建议新增：

- `python-agent/app/context/context_builder.py`
- `python-agent/app/context/context_models.py`

- [ ] `depends_on` 只解析当前轮成功结果。
- [ ] 依赖缺失或状态不是 success 时禁止启动下游 Task。
- [ ] Analysis/Writing 只读取声明依赖及对应证据。
- [ ] Search 保留有限历史用于指代消解；Analysis/Writing 默认不广播完整历史。
- [ ] required Skills 按 Task 渐进加载。
- [ ] Runtime Context 中的 Principal、Budget、Tool 白名单不能被依赖结果覆盖。
- [ ] 对每类上下文建立独立 Token Budget。

## 8.5 Agent 状态栏

后端确定性生成简短状态摘要，追加到本轮运行 Context 末尾：

```text
request_id
plan_attempt / max_replans
current_stage / total_stages
completed_task_ids
failed_task_ids
current_task
missing_aspects
used_tool_calls / budget
remaining_deadline
```

- [ ] 状态栏由代码计算，不让模型自行统计。
- [ ] 只注入模型决策需要的摘要，不包含私密正文和隐藏推理。
- [ ] 状态栏不能替代后端预算和权限检查。
- [ ] 状态更新不能破坏静态 System Prompt 的稳定前缀。

建议新增：

- `python-agent/app/context/status_bar.py`

## 8.6 HITL 三节点拆分

目标流程：

```text
GenerateDraftNode
→ Checkpoint保存DraftOutput
→ ApprovalNode interrupt
→ approve
→ SaveDraftNode
→ DraftGateway
→ Java内部草稿API
```

- [ ] `GenerateDraftNode` 只生成结构化草稿，不产生数据库副作用。
- [ ] `ApprovalNode` 只处理中断和用户决策。
- [ ] `SaveDraftNode` 使用 `run_id + task_id + draft_version` 作为稳定幂等键；同键内容 Hash 不同必须拒绝，不得因 resume 产生新请求 ID 而重复保存。
- [ ] `ApprovalNode` 的决策绑定已 checkpoint 的草稿版本与 Hash；编辑后必须新建版本并再次确认。
- [ ] Java 内部草稿 API 校验服务身份、用户身份和幂等键。
- [ ] Python `DraftGateway` 不拥有文章表 SQL。
- [ ] AI 生成 Markdown 如需进入当前文章体系，在网关或 Java 业务层确定性、安全地转成 HTML。
- [ ] 保存成功只在消息中记录 `draft_article_id`，不重复保存草稿正文。
- [ ] reject、过期、取消不产生文章记录。

建议新增：

- `python-agent/app/graph/nodes/draft_generate.py`
- `python-agent/app/graph/nodes/draft_approval.py`
- `python-agent/app/graph/nodes/draft_save.py`
- `python-agent/app/services/draft_gateway.py`
- Java 内部草稿 API 的 Controller/Service/DTO/幂等存储实现。

## 8.7 结构化 SSE

统一事件：

```text
run_started
plan_created
stage_started
 task_started
 task_completed
stage_completed
approval_required
draft_saved
citations_ready
run_completed
run_failed
run_cancelled
run_expired
```

- [ ] 每个事件携带 `request_id/run_id/event_id/sequence` 和必要的 `stage_id/task_id`；前端去重并拒绝用旧运行事件覆盖当前进度。
- [ ] 断线恢复返回持久运行状态和待审批草稿版本；若尚未支持事件重放，明确使用状态快照恢复，不承诺完整流重放。
- [ ] 不向前端发送模型隐藏推理、完整 Prompt 或敏感 Tool 参数。
- [ ] 普通流和 resume 流使用同一事件模型。
- [ ] 前端按事件更新进度，不从自然语言猜状态。

涉及文件：

- `python-agent/app/main.py`
- 建议新增 `python-agent/app/api/sse_events.py`
- `frontend/src/views/AiChat.vue`

## 8.8 迁移与切换

- [ ] Phase 2A 固定工作流先通过 Feature Flag 与旧图并存；Phase 2B 立项后，`staged_builder` 再独立切换。
- [ ] 简单 Chat、单 Search、Search→Analysis→Writing 分别做对照；shadow 禁用保存副作用和正式用户消息写入，审批/保存使用隔离环境验证。
- [ ] 各子阶段通过自身门禁后切换对应生产入口，分别保留回滚路径。
- [ ] 切换后旧 `active_workers/task_descriptions` 只保留短期兼容适配，随后删除。

## 8.9 Phase 2 验收门禁

Phase 2A 按第 8.0.1 节验收及以下通用门禁；未知依赖、拓扑分层等动态计划门禁在 Phase 2B 启用前完成。

- [ ] 未知依赖、重复依赖、自依赖和环均被拒绝。
- [ ] 每轮全部入度为 0 的 Task 固定在同一 Stage；新产生的 0 入度 Task 进入下一 Stage。
- [ ] Analysis 确实收到指定 Search TaskResult，而非仅收到用户原问题。
- [ ] Writing 依赖失败时不会生成草稿。
- [ ] 同一 Task 相同结果重放不重复消费，冲突提交拒绝，旧执行代次结果不生效。
- [ ] resume 不重新生成用户已经预览的草稿。
- [ ] SaveDraft 重放不产生第二条文章。
- [ ] 生产入口不再使用扁平并行图完成有依赖任务。

---

# Phase 3：完善结构化运行轨迹、评测与发布门禁

## 9. 阶段目标

在 Phase 0 最小回归和 Phase 1 运行标识基础上，从“能看到日志”升级为“可以复现一次 Agent 决策并判断是哪一步首次出错”，为后续 RAG、EvidenceGate、Memory 和持续进化提供数据基础。完整审计表和评测平台不阻塞 Phase 2A；2A 切换仍必须通过已有回归和对照。

## 9.1 运行轨迹

建议持久化逻辑实体：

```text
agent_run
agent_plan_attempt
agent_task_result
agent_tool_call
agent_evidence
agent_evaluation
```

- [ ] `agent_run` 记录模型、Prompt版本、工具集版本、预算、结果和成本。
- [ ] `agent_plan_attempt` 记录每轮计划，不覆盖旧计划。
- [ ] `agent_task_result` 记录 Task 最终结构化结果。
- [ ] `agent_tool_call` 记录 Tool 名、参数摘要、权限决策、状态、耗时和错误类型。
- [ ] `agent_evidence` 保存证据 ID、来源、版本、权限摘要和引用定位。
- [ ] 不保存或展示隐藏思维链；只保存可观察消息、结构化决定、工具动作和结果。
- [ ] 敏感正文按最小化原则处理，日志和评测数据脱敏。

## 9.2 Trace 层级

统一层级：

```text
trace_id
└─ request_id
   ├─ plan_attempt
   │  ├─ stage_id
   │  │  ├─ task_id
   │  │  │  ├─ model_call
   │  │  │  ├─ tool_call
   │  │  │  └─ evidence
   │  │  └─ barrier
   │  └─ evidence_gate
   └─ final_synthesis
```

- [ ] Langfuse span 与业务 ID 对齐。
- [ ] CostTracker 接入真实模型调用和 Tool 调用。
- [ ] Reflector/EvidenceGate/Memory/RAG 子步骤都具有可检索 span。
- [ ] Langfuse 未配置时仍保留本地结构化业务审计，不能静默失去关键数据。

## 9.3 评测数据集

所有评测资产放入 `test/`：

```text
test/eval/agent/
test/eval/rag/
test/eval/memory/
test/eval/security/
```

首批数据来源：

- 真实但已脱敏的用户 Query；
- 用户纠正和点踩轨迹；
- 当前已知故障案例；
- 权限越界对抗用例；
- Search→Analysis→Writing 依赖用例；
- HITL重复resume和取消用例；
- 无结果、索引延迟和下游超时用例。

## 9.4 指标体系

Agent：

```text
Task Success Rate
Pass@1
Pass@k（探索能力）
Pass^k（连续稳定性）
平均Stage/Task/Tool调用数
平均Token与单任务成本
p50/p95端到端延迟
人工接管率
```

RAG：

```text
Chunk Recall@20
MRR / nDCG@10
Rerank Recall@8
Context Precision / Recall
Faithfulness
Citation Precision
权限泄漏率
平均注入Token
索引新鲜度
```

Memory：

```text
基础回忆
多会话消歧
冲突更新
时间推理
主动服务
跨用户/跨项目泄漏率
过期或superseded误召回率
```

安全门禁：

```text
未授权Tool执行率 = 0
跨用户数据泄漏率 = 0
高风险操作绕过HITL率 = 0
引用不存在率 = 0
```

## 9.5 首错归因

每条失败轨迹至少记录：

```text
first_error_step
primary_category
secondary_categories
task_id/tool_name
evidence
recoverable
confidence
```

- [ ] 定位第一个使任务偏离的错误，而不是最后一个异常。
- [ ] 区分需求理解、上下文缺失、规划错误、工具错误、权限错误、证据不足、生成幻觉和基础设施故障。
- [ ] 规则可确定判断的先规则筛选，再由 LLM 辅助归因。
- [ ] LLM 归因不能直接修改生产 Prompt 或 Skill。

## 9.6 Feature Flag 与消融

- [ ] 主要能力必须可以独立关闭：staged graph、Memory、Reranker、Neighbor Expand、EvidenceGate、replan。
- [ ] Feature Flag 决策记录到 `agent_run`。
- [ ] 评测时支持裸模型/基础图/目标图消融对比。
- [ ] 每次 Prompt 变更保存确定性渲染快照和版本。

## 9.7 Phase 3 验收门禁

- [ ] 任一失败运行可以从 `request_id` 追踪到 Plan、Task、Tool 和证据。
- [ ] 能区分检索失败与生成失败。
- [ ] 当前 RAG baseline 已冻结并形成报告。
- [ ] 权限、HITL、已启用编排和引用都有可重复验证用例；动态 DAG 尚未立项时不作为 Phase 3 的前置要求。
- [ ] 关键功能支持 Feature Flag 回滚。
- [ ] 发布报告同时包含质量、成本、延迟和安全指标。

---

# Phase 4：可靠索引、结构化分片与目标 RAG/Citation

## 10. 阶段目标

先把索引变成可重建、可切换、可回滚的数据产品，再升级分片和检索，避免在不可靠生命周期上继续堆算法。

## 10.1 索引生命周期与一致性

- [ ] 消息携带 `article_id/article_version/source_hash/event_type`。
- [ ] 消费前查询 MySQL 最新状态和版本。
- [ ] 旧事件不能覆盖新版本。
- [ ] 新版本先完成解析、分片、Embedding、bulk 校验，再切换有效版本。
- [ ] PUBLISH/UPDATE/UNPUBLISH/DELETE 全生命周期明确。
- [ ] bulk 任一 item 失败时整次任务不能标记成功。
- [ ] Embedding 改为受限批处理。
- [ ] 删除失败不能吞异常后 ack。
- [ ] 建立事务 Outbox、可重试消费、持久 DLQ 和周期对账。

### 10.1.1 单篇文章版本发布协议

整库 Alias 切换与单篇文章更新分别实现。Alias 用于 Mapping/分片/Embedding 方案迁移；一篇文章的多个 Chunk 不能依靠一次普通 bulk 获得整体发布原子性。

建议以数据库单调递增 `article_version` 表示业务版本，`source_hash` 表示内容与索引相关元数据快照，`index_generation` 表示解析/分片/模型方案。更新时间或 Hash 单独使用不能可靠表达事件先后。

```text
文章事务：更新 article_version + 写入 Outbox
  ↓
消费者读取明确版本的内容快照，创建幂等构建任务
  ↓
解析/分片/Embedding，写入未发布 Chunk 集合
  ↓
逐项检查 bulk + 数量/Hash 校验 + 等待检索可见
  ↓
事务内重新核对最新版本、业务状态和执行代次
  ↓
条件更新发布记录（有效文章版本 + 索引代次）
  ↓
查询经发布记录与 MySQL 最新业务状态复核后使用
  ↓
延迟清理旧版本，保留迁移/排障所需窗口
```

- [ ] Chunk ID 至少包含 `article_id/article_version/index_generation/chunk_index`，构建期间不覆盖正在读取的旧块。
- [ ] 发布记录保存预期 Chunk 数、实际成功数、Hash、构建状态及有效版本；部分成功不可发布。
- [ ] 构建前和发布前均核对当前版本；发布使用条件更新，旧构建不能覆盖新发布记录。相同构建键重投幂等，过时代次只能清理自身产物。
- [ ] 检索只使用已发布且与 MySQL 当前版本、状态和权限一致的候选。复核须发生在正文进入 LLM Context、Citation、卡片和正文日志之前；新版本未就绪时，首版跳过该文章并标记索引滞后，不把旧正文当作最新内容。
- [ ] 查询明确限制可参与召回的版本，并为复核淘汰候选配置有界补召回；仅在最终 TopK 后过滤而不补召回可能严重降低有效召回量，必须纳入评测。
- [ ] 发布记录与 ES 不存在跨库事务：ES 构建完成但数据库发布失败时保留可重试任务/孤立产物清理；数据库已发布但检索不可用时明确失败或跳过，不静默回退过时证据。
- [ ] DELETE/UNPUBLISH/权限变化先在 MySQL 阻止使用，随后可靠传播 ES 清理；即使旧事件再次到达，也不得重新发布已失效正文。
- [ ] 并发更新、旧事件晚到、构建中删除、bulk 部分失败、进程在发布前后退出都纳入回归。

首版可采用发布记录加候选版本复核的方案，具体查询限制方式在编码前固定。若希望更新期间继续提供旧正文，必须另行定义产品可接受的过期窗口和引用标记，不能默认把“旧块未删除”等同于“允许使用”。

建议新增 Java 模块：

- `src/main/java/com/easyjob/agent/index/ArticleIndexVersionService.java`
- `src/main/java/com/easyjob/agent/index/ArticleIndexOutboxService.java`
- `src/main/java/com/easyjob/agent/index/ArticleIndexReconciliationService.java`

## 10.2 版本索引与 Alias

目标：

```text
article_vectors_v2
article_vectors_read alias
article_vectors_write alias
```

- [ ] Mapping 一次定义目标字段。
- [ ] 回灌只选择允许索引的文章。
- [ ] 记录 `parser_version/chunker_version/tokenizer_name/embedding_model`。
- [ ] Shadow 查询比较旧索引和新索引。
- [ ] 原子切换 read alias。
- [ ] 保留旧索引回滚窗口。
- [ ] 回灌与增量事件有明确水位：切换前重放回灌期间的变更并完成对账，不能只依据初始全量数量相等。
- [ ] Alias 回滚后仍按 MySQL 最新版本与权限复核；旧索引缺失新数据时显式跳过/报告，不恢复已删除文章或旧权限。

## 10.3 统一 Block 和结构化 HTML 分片

建议新增：

- `src/main/java/com/easyjob/agent/chunk/DocumentBlock.java`
- `src/main/java/com/easyjob/agent/chunk/HtmlDocumentParser.java`
- `src/main/java/com/easyjob/agent/chunk/StructuredChunkAssembler.java`
- `src/main/java/com/easyjob/agent/chunk/CodeBlockSplitter.java`
- `src/main/java/com/easyjob/agent/chunk/TableBlockSplitter.java`
- `src/main/java/com/easyjob/agent/chunk/ChunkingProperties.java`
- `src/main/java/com/easyjob/agent/chunk/TokenCounter.java`

- [ ] 用 Jsoup DOM 遍历替代 `.text()`。
- [ ] 支持 HEADING、PARAGRAPH、LIST、BLOCKQUOTE、CODE、TABLE 等 Block。
- [ ] 为正文保存 `heading_path`。
- [ ] 同标题路径下按自然边界聚合。
- [ ] 只有单个语义单元被迫拆开时才 overlap。
- [ ] 代码块保持语言、缩进和必要签名。
- [ ] 长表格按“表头 + 行组”拆分并重复表头。
- [ ] 解析覆盖率不足、空块、超限块或块数超限时失败，不静默截断。

首轮参数只是实验组：

```text
A: target=320, hardMax=512, overlap=48
B: target=480, hardMax=700, overlap=64
C: target=768, hardMax=1024, overlap=96
```

最终参数由 Phase 3 评测决定。

## 10.4 索引字段

至少包括：

```text
chunk_id
article_id
article_version
source_hash
chunk_index
chunk_content
heading_path
block_types
language
token_count
source_start/source_end
prev_chunk_id/next_chunk_id
category_id
tags
publish_time/update_time
status/is_deleted/visibility/user_id
parser_version/chunker_version
content_vector
```

检索文本与展示文本分离：

```text
embedding_text = article_title + heading_path + block_context + chunk_content
展示/Citation = 原始chunk_content + 原文定位
```

## 10.5 同 Chunk 粒度 Hybrid

目标检索链：

```text
Query Rewrite
→ FilterResolver
→ Principal ACL
→ KNN TopN(article_vectors_v2)
→ BM25 TopN(article_vectors_v2)
→ 按chunk_id手写RRF
→ Reranker
→ 单文章多样性控制
→ 最终核心块±1邻块扩展
→ CitationBuilder
→ Search Subagent
```

- [ ] KNN 和 BM25 使用同一 `chunk_id`。
- [ ] 不再长期依赖 `article_vectors + article` 双索引融合。
- [ ] 邻块扩展只发生在 Reranker 后。
- [ ] 邻块必须校验同文章、版本、权限和标题边界。
- [ ] 相邻块只提供上下文，不继承核心块相关性分数。
- [ ] Search Subagent 回传压缩结果、Citation、Evidence 和 Retrieval Trace。

建议新增：

- `python-agent/app/services/neighbor_expander.py`
- 重构 `python-agent/app/services/retrieval_service.py`

## 10.6 Citation 端到端闭环

- [ ] CitationBuilder 同时产生 LLM Context 和前端 Payload。
- [ ] 平台和 Web 证据使用统一编号模型。
- [ ] 最终回答的事实性陈述引用可映射到 `evidence_id`。
- [ ] 普通流与 resume 流统一下发 `citations_ready`。
- [ ] 前端安全渲染引用，不使用不受控 HTML 拼接。
- [ ] 点击平台引用时校验文章仍可访问；Web 引用显示 URL 和摘要。
- [ ] MySQL 回查失败、文章删除或权限变化时 Citation 失效，不继续展示旧数据。

## 10.7 Phase 4 验收门禁

- [ ] UPDATE 构建失败时旧索引仍可服务。
- [ ] 旧消息不能覆盖新文章版本。
- [ ] 未完整发布的 Chunk 不进入回答；同篇文章的新旧版本不混用。
- [ ] 新版本未就绪、发布后进程退出以及整库切换/回滚均有明确读取行为和回归结果。
- [ ] HTML 标题、段落、列表、代码和表格可追踪。
- [ ] 不存在空 Chunk、静默截断和超过 hard max 的 Chunk。
- [ ] KNN/BM25 以同一 `chunk_id` 融合。
- [ ] ACL 在召回前生效，权限泄漏用例为 0。
- [ ] 回答引用都存在 Payload，Payload 能支撑对应陈述。
- [ ] 新方案 Recall/nDCG/Citation Precision 不低于 Phase 3 baseline 和已确认门槛。
- [ ] Alias 切换与回滚流程可执行。

---

# Phase 5：EvidenceGate、EvidencePool 与增量重规划

## 11. 阶段目标

把当前单一 Reflector 升级成“确定性验证优先、模型评审补充、修复路径分流”的质量控制闭环。

## 11.1 EvidencePool

- [ ] Evidence 使用稳定 `evidence_id/doc_key` 去重。
- [ ] 保存来源、文章/网页版本、原文定位、权限摘要、aspect 和首次出现 attempt。
- [ ] 只把通过权限和基础相关性检查的证据加入 active pool。
- [ ] Planner 只读取 aspect 摘要和缺失项，不读取全部原文。
- [ ] Analysis/Writing 按依赖和 carried evidence 精确取原文。

建议新增：

- `python-agent/app/evidence/models.py`
- `python-agent/app/evidence/evidence_pool.py`
- `python-agent/app/evidence/evidence_resolver.py`

## 11.2 EvidenceGate

确定性检查优先：

- [ ] 必需 Task 是否成功；
- [ ] Search 的 `retrieved_count` 是否大于 0；
- [ ] Citation/Evidence 是否真实存在；
- [ ] 当前 Principal 是否仍有权限；
- [ ] 文章状态和版本是否仍有效；
- [ ] required aspects 是否有证据覆盖；
- [ ] Tool 是否真实成功；
- [ ] 最终事实是否存在证据映射。

模型评审补充：

- 证据相关性；
- 覆盖度；
- 回答忠实度；
- 完整性；
- 表达和格式。

建议新增：

- `python-agent/app/graph/nodes/evidence_gate.py`
- `python-agent/app/evaluation/retrieval_quality.py`
- `python-agent/app/evaluation/generation_quality.py`

## 11.3 修复路径分流

```text
权限/契约/必需依赖错误 → fail_fast
必需基础设施不可用     → 明确失败；仅允许已有预算策略下的有限重试
检索瞬时故障         → 受预算约束retry_stage
证据不足             → incremental replan
证据充分但表达不好   → regenerate，仅重跑生成
可选补充任务失败     → 明确标记后才允许degrade
```

- [ ] 首版只启用已经有评测覆盖的分支。
- [ ] 任何 degrade 都必须由下游 Task 声明可容忍。
- [ ] 与第 1.3 节保持一致：可选组件故障不必等到 Phase 5 才能受控降级；Phase 5 新增的是动态质量判定和修复分流。
- [ ] 不允许依赖缺失后让模型凭常识补全。

## 11.4 增量 replan

- [ ] `plan_attempt` 每次递增并归档旧结果。
- [ ] Planner 输入必须加入上一计划、反馈、已覆盖 aspect、缺失 aspect、已试 query 和 mode。
- [ ] 第二轮默认只补缺失证据，不全量推翻第一轮。
- [ ] `retrieval_history` 跨 attempt 保留。
- [ ] 新检索排除已见 `doc_key` 或改变检索范围/措辞/模式。
- [ ] 旧 Search 证据可以复用；旧 Analysis/Writing 因新证据加入而逻辑失效。
- [ ] 最终合成只读取当前有效派生结果。

## 11.5 无进展检测和预算

- [ ] 比较两轮证据集合重合度。
- [ ] 高重合且无新增 aspect 时停止重试。
- [ ] `ExecutionBudget` 至少约束：
  - max_replans；
  - max_stage_retries；
  - max_tool_calls_per_task；
  - max_total_tasks；
  - max_input/output_tokens；
  - deadline_ts。
- [ ] 预算耗尽时明确告知证据不足，不编造完整答案。

## 11.6 Phase 5 验收门禁

- [ ] 零召回由确定性规则识别，不依赖 LLM 猜测。
- [ ] 格式问题不会重跑检索。
- [ ] replan 后 Task 或检索条件发生实质变化。
- [ ] 新证据加入后旧 Analysis/Writing 不进入最终合成。
- [ ] 两轮无进展时停止消耗预算。
- [ ] Evidence 权限变化后不可继续注入。
- [ ] 任意循环均受次数、Tool和deadline约束。

---

# Phase 6：长期记忆 V2

## 12. 阶段目标

在可信 Principal 和阶段化 Task 基础上，实现可审计、可冲突替代、按用户/项目隔离的两级长期记忆。

## 12.1 模块拆分

建议从单体 `memory.py` 拆为：

- `python-agent/app/memory/models.py`
- `python-agent/app/memory/key_resolver.py`
- `python-agent/app/memory/repository.py`
- `python-agent/app/memory/index_service.py`
- `python-agent/app/memory/extraction_service.py`
- `python-agent/app/memory/recall_service.py`
- `python-agent/app/memory/reconciliation_service.py`

## 12.2 V2 数据模型

- [ ] 区分用户画像与事件记忆。
- [ ] 事件类型：`constraint/decision/goal`。
- [ ] 作用域：`USER/PROJECT`。
- [ ] 状态：`active/superseded/completed/cancelled/expired`。
- [ ] 增加 `memory_key/memory_value/content`。
- [ ] 增加 `supersedes_memory_id/source_message_id/content_hash/expires_at`。
- [ ] LLM 只能提出候选，最终 canonical key 由确定性 Resolver 生成。
- [ ] 模糊冲突进入待确认或拒绝写入，不静默覆盖。

## 12.3 提取可靠性

- [ ] 最终 assistant 消息成功持久化后才触发提取。
- [ ] interrupt、失败 Task、未确认建议和原始 Tool 输出不形成 active memory。
- [ ] 增加 `last_memory_extracted_message_id` 水位。
- [ ] 使用 `user_id + source_range + content_hash` 幂等。
- [ ] 以 Outbox/队列替代进程内 `asyncio.create_task()` 作为可靠投递保障。
- [ ] 提取失败可重试、可进入 DLQ、可对账。

## 12.4 冲突和生命周期

- [ ] 同 scope、type、key 的新 constraint 通过事务替代旧记录。
- [ ] PROJECT 记录只在当前项目覆盖 USER 记录，不全局 supersede。
- [ ] Decision 保留历史替代链。
- [ ] Goal 只能由明确用户确认或确定性业务事件完成/取消。
- [ ] 用户删除记忆、项目或账号时，MySQL、ES、缓存和备份策略闭环。

## 12.5 规划前召回

- [ ] 请求入口构造 `MemoryQuery`，自动填可信 user/project scope。
- [ ] 召回精简画像、active constraints、相关 decisions 和 active goals。
- [ ] ES KNN 前置过滤 user/scope/status/type/expiry。
- [ ] MySQL 使用同样条件复核并恢复 ES 排序。
- [ ] 结果进入独立 `memory_context.plan_context`。
- [ ] 不把 Memory 伪装为用户消息，不再次进入会话摘要。

## 12.6 Task 级召回

扩展 PlannedTask：

```text
goal_refs
memory_requirement.enabled
memory_requirement.memory_types
memory_requirement.scope
memory_requirement.top_k
```

- [ ] SubagentRunner 前按 Task instruction 召回。
- [ ] 每个 Task 只获得声明的类型、scope 和数量。
- [ ] Task 不能扩大 Planner 和 Principal 的允许范围。
- [ ] `current_task_memory` 与短期历史、依赖结果分离。
- [ ] Memory 注入时标记为不可信历史事实候选，禁止当成系统指令执行。

## 12.7 ES V2 与迁移

目标：

```text
user_memories_v2
user_memories_read alias
user_memories_write alias
```

- [ ] 新建正式 MySQL migration。
- [ ] 旧无类型事件标记 legacy 或重新提取，不自动升级为强约束。
- [ ] 回灌 active V2 数据并校验 user/scope/status/维度。
- [ ] Shadow recall 对比。
- [ ] Alias 原子切换并保留回滚窗口。

## 12.8 Phase 6 验收门禁

- [ ] 跨用户、跨项目 Memory 泄漏率为 0。
- [ ] 新 constraint 生效后旧值可审计但不再正常召回。
- [ ] completed/cancelled/expired goal 不参与普通规划。
- [ ] ES 脏候选不能绕过 MySQL。
- [ ] 长期记忆不会写回短期历史或被再次摘要。
- [ ] 每个 Task 只获得声明允许的记忆。
- [ ] 索引失败可重放、可对账。
- [ ] 基础回忆、多会话消歧和冲突更新评测达到已确认门槛。

---

# Phase 7：稳定性、性能、治理与离线持续进化

## 13. 阶段目标

只有前述正确性、安全和评测闭环稳定后，才优化成本、延迟和自动改进能力。

## 13.1 Tool Guard 深化

- [ ] 每个 Tool 定义独立 Pydantic/JSON Schema。
- [ ] 校验字符串长度、集合数量、URL域名、路径范围和资源权限。
- [ ] 返回值按字段和类型裁剪，不使用统一字符截断破坏 JSON。
- [ ] 区分 timeout、rate_limit、permission_denied、validation_error、downstream_error。
- [ ] Tool 描述补充“何时使用、何时禁止、参数示例、返回结构、成本和副作用”。

## 13.2 上下文压缩

- [ ] 优先依靠 Subagent 隔离和 Task Context 裁剪，而不是先做通用摘要。
- [ ] 监控 Context 使用率，达到阈值后批量压缩 Tool 原始结果。
- [ ] 压缩必须面向当前 Task 和未完成 aspect。
- [ ] 摘要保留 Citation/Evidence ID，支持回溯原文。
- [ ] 静态 System Prompt 和 Tool 定义保持稳定前缀。
- [ ] 压缩前后在评测集对比忠实度、成本和延迟。

## 13.3 缓存

- [ ] 先修正会话缓存写入顺序：数据库提交成功后再更新或删除缓存。
- [ ] RAG 缓存 key 包含 Principal/scope、filter、索引版本、Embedding/Chunker/Reranker版本。
- [ ] 缓存值只保存当前 Principal 可见结果。
- [ ] 权限变化、文章更新、索引切换具有失效机制。
- [ ] Planner 默认不缓存；只有输入、Principal、Memory、索引和Prompt版本全部稳定时才重新评估。
- [ ] 通用 Tool 结果只缓存明确无用户敏感性、可幂等、可定义TTL的数据。

## 13.4 可观测性和治理

- [ ] Dashboard 展示成功率、Pass^k、成本、Token、p95、Tool错误、重规划率、权限拒绝和索引延迟。
- [ ] 建立 Prompt、Skill、Tool、模型和索引版本关联。
- [ ] 对高成本、高失败率和重复调用建立告警。
- [ ] 定期做 Feature 消融，删除已经没有收益的复杂机制。
- [ ] 日志遵守脱敏、最小保留和删除策略。

## 13.5 离线持续进化

采用双循环：

```text
在线执行循环
  只完成任务、记录不可变轨迹和反馈

离线进化循环
  聚合轨迹
  → 首错归因
  → 生成最小改进提案
  → 独立验证集与保留集
  → 人工审核
  → 版本化发布
  → 可回滚
```

- [ ] 经验可以沉淀为知识、Skill、确定性程序或模型训练提案。
- [ ] 一次成功/失败不能直接修改正式能力。
- [ ] 网页、邮件、Tool输出和Memory都属于不可信证据，不能直接写成长期指令。
- [ ] 待验证 Prompt/Skill/代码与正式版本隔离。
- [ ] Agent 不能修改批准自身更新的验证器、安全门、审计日志和回滚版本。
- [ ] 更新必须同时改善触发失败集，且不破坏保留任务集和安全集。

## 13.6 Phase 7 验收门禁

- [ ] 非法 Tool 参数在执行前被拒绝。
- [ ] 缓存不会跨用户、项目、权限或索引版本污染。
- [ ] 压缩后 Faithfulness 不低于已确认门槛。
- [ ] 每项高阶能力有独立 Feature Flag 和消融结果。
- [ ] 自动生成的改进不能绕过独立验证与人工审批。
- [ ] 任何版本可以快速回滚到最近稳定版本。

---

## 14. 全局验收标准

以下是完整目标架构的验收标准。首轮按第 1.5 节范围和 Phase 0、1、2A 门禁验收，不要求提前完成 Phase 2B 或 Phase 4～7。

### 14.1 编排正确性

- Planner 输出 Task 和依赖，确定性代码生成 Stage；
- 同 Stage 只有无依赖任务并行；
- 下游只读取声明依赖；
- 缺失或失败的必需依赖不会被模型补全；
- Barrier 能发现缺失、重复和失败结果；
- 所有循环受预算和 deadline 限制。
- 同会话非终态运行唯一，重复请求幂等，终态和副作用不被迟到结果覆盖。

### 14.2 权限安全

- Principal 全链路来自可信服务端；
- 用户无法通过自然语言、Planner或Tool参数提权；
- RAG、Memory、会话、Checkpoint和草稿均进行资源授权；
- 无权限数据不进入候选、Context、日志和前端；
- Subagent 和 Tool 只能收窄权限。

### 14.3 RAG 与证据

- Query Rewrite、Filter、Hybrid、Rerank、Neighbor、Citation 契约完整；
- KNN/BM25 在同一 Chunk 粒度融合；
- 每个引用可定位原始证据和版本；
- EvidenceGate 能区分检索不足与生成问题；
- 检索失败时明确说明不足，不用模型常识伪造证据。

### 14.4 HITL 与副作用

- 草稿生成、审批和保存节点分离；
- resume 不重放草稿生成；
- 保存由 Java 业务服务确定性执行；
- 同一幂等键只生成一个草稿；
- 审批绑定已预览内容的版本与 Hash，修改后再次审批；
- reject/expired 或已接受 cancel 的运行不再产生保存副作用；提交先完成时如实返回保存状态。

### 14.5 Memory

- 短期历史、Checkpoint、长期画像、事件记忆和TaskResult职责分离；
- Memory 支持类型、scope、状态和冲突链；
- 规划前和 Task 级召回均受 Principal、类型和 Token Budget 限制；
- Memory 不作为系统指令执行；
- MySQL/ES 状态可重建、可对账。

### 14.6 可靠性和评测

- 每次运行可以按 request_id 复盘；
- 失败能够定位首错步骤；
- 关键改造有 baseline、对照组和回归结果；
- 最小回归从 Phase 0 开始维护，Phase 3 扩展后保持兼容；
- 可选能力降级有结构化状态和证据边界，权限与契约失败不降级为成功；
- 质量、成本、延迟和安全同时纳入发布门禁；
- 关键业务关注 Pass^k，而不是只展示 Pass@k；
- 所有高阶能力均可关闭和回滚。

---

## 15. 编码前需明确的决策与配置

这些事项在对应阶段编码前写入决策记录，不要求首轮一次确认全部问题。普通工程配置由实施者依据仓库现状提出并记录默认值；公开部署、可见性规则、数据保留和共享范围等产品决策在无既定授权时需用户确认。Phase 2B、Memory V2 等后续事项不阻塞首轮。

1. 项目正式数据库 migration 工具和目录。
2. Java→Python 服务间认证方式，以及 Python Agent 是否允许独立公网访问。
3. `Principal.role/visible_scopes` 最终枚举和关注者可见性规则。
4. Java 内部草稿 API 路径、鉴权、幂等表设计和 Markdown→HTML 转换位置。
5. 文章 HTML 白名单与历史内容安全清洗策略。
6. `agent_run/task/evidence` 使用新表、现有日志系统还是组合存储。
7. 运行轨迹正文、Tool参数和Evidence的保留期限与脱敏规则。
8. `article_version` 的迁移与递增规则、发布记录载体及查询版本限制方式；默认方向见第 10.1.1 节，不用 Hash 或更新时间替代版本顺序。
9. `article_vectors_v2` Alias 名称、双写周期和旧索引保留期。
10. 与当前 Embedding 模型对齐的 TokenCounter。
11. Chunk参数、候选数、RRF窗口、Rerank TopK 和上下文 Token Budget。
12. Memory V2 扩展旧表还是新建表。
13. Memory canonical key 注册表和模糊冲突待确认机制。
14. PROJECT scope 是否支持多人共享，以及成员变更后的权限处理。
15. Goal 完成状态由用户确认、业务事件还是 Main Agent 提议触发。
16. 评测集规模、人工标注负责人和正式发布门槛。
17. Langfuse或其他观测平台的生产配置与数据合规边界。
18. 同会话运行占用、租约/执行代次、状态转换与 Java 保存裁决的事务载体；运行语义见第 7.1.1 节。
19. 首轮工作流路由范围、可选能力的降级契约、回归用例与可接受延迟/成本。

---

## 16. 明确延后的能力

以下能力不是当前目标代码的前置条件，只有前述阶段通过评测后才重新立项：

| 能力 | 延后原因 |
|---|---|
| GraphRAG / RAPTOR | 当前 RAG 契约、ACL、分片和评测尚未稳定 |
| CRAG 全量 Grader | 与 Reranker/EvidenceGate职责重叠，固定增加模型成本 |
| 主动工具发现 | 当前 Tool 数量不足；应先执行静态白名单 |
| A2A、去中心化Agent、自由消息总线 | 当前中心化 Task/Result 协议足够且更易审计 |
| 多Agent自由辩论 | 没有引入新证据时只增加成本和错误传播 |
| 通用 Code Interpreter | 用户数据、依赖供应链、沙箱和审计成本较高 |
| Planner 通用缓存 | Principal、Memory、Prompt、索引和重规划历史会改变计划 |
| 自动修改 Prompt/Skill | 缺少独立验证时会把一次错误永久化 |
| 模型 SFT/RL | 当前主要瓶颈是 Harness 和数据链路，不是底座能力 |
| 真正 Markdown 编辑闭环 | 当前产品事实源是 wangEditor HTML，需独立产品确认 |
| Java/Python AST代码分片、多模态图片检索 | 属于结构化HTML分片稳定后的增益项 |
| 自动标签、自动分类、封面生成 | 非核心链路，且可能污染业务数据 |
| 推荐和通知系统扩展 | 属于博客产品线，不是Agent控制面前置依赖 |

---

## 17. 分阶段文件总表

| 阶段 | 主要修改文件 | 主要新增文件 |
|---|---|---|
| Phase 0 | `main.py`、`search_worker.py`、`query_rewrite.py`、`retrieval_service.py`、`es_client.py`、`memory.py`、`writing_worker.py`、`conversation.py`、Java `AgentService.java` | `citation_builder.py`、`models/draft.py`、`run_service.py`、`state_factory.py`、`test/eval/agent_baseline/**` |
| Phase 1 | `main.py`、`tool_registry.py`、`tool_executor.py`、各Worker、检索服务、Java会话/保存边界 | `security/principal.py`、`authorization_service.py`、`request_identity.py`、持久运行状态/租约与幂等存储 |
| Phase 2A | `builder.py`、`state.py`、Worker/Synthesizer、`AiChat.vue` | 固定工作流与最小TaskResult、Draft三节点、`draft_gateway.py`、Java内部草稿API、`sse_events.py` |
| Phase 2B（按需） | Phase 2A图、Planner/Worker、`AiChat.vue` | `staged_plan.py`、`staged_state.py`、`staged_planner.py`、`stage_executor.py`、`staged_builder.py`、`context_builder.py`、`status_bar.py` |
| Phase 3 | `observability.py`、日志和各节点埋点 | Agent运行审计存储、`evaluation/`模块、`test/eval/**`、Feature Flag与Prompt快照工具 |
| Phase 4 | `DocumentChunkService.java`、`ArticleVectorListener.java`、`EsVectorStore.java`、`DocumentChunk.java`、Python检索链、`AiChat.vue` | Java `agent/chunk/**`、`agent/index/**`、`neighbor_expander.py`、V2索引migration/回灌工具 |
| Phase 5 | staged state/builder、Planner、Search/Analysis/Writing、Synthesizer | `evidence/**`、`evidence_gate.py`、Retrieval/Generation Quality模型 |
| Phase 6 | `memory.py`、staged plan/state、RunService、ES客户端 | `memory/**`、Memory V2 migration、ES V2索引和对账服务 |
| Phase 7 | Tool、Context、Cache、Observability | `tool_guard.py`、`cache_key_factory.py`、离线进化流水线和治理看板 |

---

## 18. 执行状态维护规则

### 18.1 当前实施记录（2026-09-30）

状态：**主 Agent 直接执行、子代理按需委派已接入真实入口；离线验证通过，生产门禁尚未验收。完整路线仍未全部完成。**

- 代码提交：工作区修改，尚未提交或部署。
- 编排：`main_agent.py` 每轮在本次调用内直接分析，用结构化 `MainDecision` 选择 `answer/retrieve/delegate/write_draft`。已删除顶层 `analyze` 和独立 Main 分析调用；`answer.reply` 已是完整答案，非回答动作可同时用 `artifacts` 输出已完成正文，代码继承声明依赖的证据并保存供后续任务复用。`action_runtime.py` 执行外部动作后把结果与状态回到 Main；不要求预先生成全部计划，也不增加必经分类模型。代码校验 Task ID/技能/能力/依赖/环；只读委派仍有 DAG plan，按依赖就绪和并发名额执行，已移除整阶段 Barrier。Workflow 是草稿生成/审批/保存的固定业务边界。Analysis/Writing 仅读取声明成功依赖，草稿保存或放弃后确定性交付结果，不再调用模型。默认 8 轮、全运行 8 个 Task（包括 Main 产物）、并发 3、Main 上下文 96000 字符；成功结果不可覆盖。Main 读取完整成功结果和引用，不再按每项前缀截断，整体超预算明确停止；状态和实际参数历史用于决策。`get_graph()` 已使用动态新图，旧扁平图仅用于历史回归。
- 身份：Java JWT → 服务 key + 可信用户头 → Python Principal；所有会话、运行、历史、取消、恢复接口复核所属用户；图片限于本人上传目录。当前只支持现有公共已发布文章范围，未新增项目或关注者权限。
- 运行：新增 MySQL `agent_run/agent_run_event`、活动会话唯一约束、请求幂等、deadline 与执行 token、审批运行与内容 Hash、终态和消息事务提交。取消与 Java 草稿提交使用同库行锁裁决；保存结果丢失可通过请求重放或运行查询恢复。
- 草稿：独立生成/审批/保存节点，修改后再次审批；真实路径改为 Java 内部 API，Java 清洗 HTML 并保存业务草稿，不再 Python 直写文章表。
- 自纠错：局部动作格式、答案/产物引用修正最多一次，引用修正保留原动作、参数和证据依赖，不重新检索；证据不足允许改变一次策略，只读超时/连接故障允许原参数重试一次，两者共享一次恢复预算，并可复用成功结果。已成功或证据不足的相同参数更换 ID 或执行者不能绕过指纹；再次失败或预算耗尽停止。权限、来源变化、取消/fencing、审批与保存失败不软重试。旧全局 Reflector 不在真实入口。当前门禁仍只检查依赖、引用存在性、来源发布状态和内容 Hash，不宣称完成语义忠实度、aspect coverage 与完整 Phase 5。
- RAG：保留旧索引融合兼容层；候选经 MySQL 发布状态复核，以当前业务正文作为证据，低相关性不强制回填；平台/联网引用可保存和展示。正式结构化 Chunk、单文档版本发布、索引 Outbox/别名切换尚未实施。
- 迁移：`001_message_metadata.sql`、`002_agent_runs.sql`，命令 `python -m app.migrate`；本次没有连接真实数据库执行迁移，启动只检查结构与关键唯一约束。
- 流式交互：Python 实时发布公开处理说明、任务计划、活动与终态，前端按 ID 更新可折叠记录并显示并行子任务；独立草稿卡片支持保存/放弃/修改后再次确认。答案在来源校验与结果提交后分段传输，保留完整回复兼容；不是模型生成时逐 token 展示。聊天/恢复共用解析器，刷新恢复待审批元数据。当前未持久回放活动，未完成断线续接、历史时间线及第 8.7 节完整事件信封。
- 验证：本轮 87 个 Python 离线用例、6 个前端 SSE 协议用例、`pip check` 通过。覆盖同次调用生成/消费 Main 产物、产物身份与证据边界、完整结果输入、超预算保留结果、原参数故障限次重试、动作观察、部分成功复用、依赖就绪、并发/轮数/任务预算、取消、按轮活动和终端草稿。此前 8 个 Java 代理/认证/HTML/幂等边界用例、Java 编译、前端构建与离线浏览器交互通过，本轮未改 Java/前端组件，未重复这些检查。正式模型决策/质量评测、真实数据库竞争、Redis Stack 重启恢复与跨服务联调仍是发布门禁；旧阶段图 Checkpoint 升级前须处理完，委派尚无逐子任务持久恢复。
- 部署与回滚：`docs/archive/setup/STAGED_SETUP.md`；必须配套更新 Java/Python/前端并配置服务认证。Java/Python 当前共用 MySQL 运行协调账本，不能直接按不同数据库的微服务模式部署。
- 尚待后续阶段：Memory V2、可靠记忆提取投递、可靠版本索引、完整语义 EvidenceGate、评测 runner/数据集/成本门禁、生产监控与治理。首轮范围按本次用户要求扩展到 Main Agent + Subagent 核心编排，不把其余长期目标一并标为已完成。

### 18.2 后续阶段维护要求

后续每完成一个 Phase，必须更新本文：

```text
状态：未开始 / 进行中 / 已完成 / 已回滚
代码提交：commit SHA
数据库迁移：版本号
索引版本：名称与alias
评测报告：路径
已知偏差：仍未完成项
```

禁止出现：

- 文档写“已完成”，运行入口仍走旧代码；
- 示例代码存在，但真实构图未引用；
- Mapping已写文档，但索引未重建；
- Tool白名单已配置，但Worker仍调用 `get_all_tools()`；
- Phase 2A 已交付却把 Phase 2B 或后续目标一并标为已完成；
- 评测只跑成功案例，不包含权限、并发、失败和回滚路径；
- 以命令执行成功代替业务验收。

---

## 19. 参考资料

项目内资料：

- [`17-harness-engineering-optimization.md`](17-harness-engineering-optimization.md)
- [`18-optimization-roadmap.md`](18-optimization-roadmap.md)
- [`19-hitl-draft-persistence.md`](19-hitl-draft-persistence.md)
- [`20-rag-optimization.md`](20-rag-optimization.md)
- [`21-main-agent-subagent-staged-architecture.md`](21-main-agent-subagent-staged-architecture.md)
- [`22-long-term-memory-v2.md`](../../agent/memory/22-long-term-memory-v2.md)
- [`23-structured-article-chunking.md`](23-structured-article-chunking.md)
- `docs/reference/ai-agent-book/AI-Agents-in-Depth-zh-CN.pdf`

外部设计参考：

- [LangGraph Interrupts：恢复会重新执行被中断节点，副作用需要幂等](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Elasticsearch Aliases：整库索引切换与原子Alias操作](https://www.elastic.co/guide/en/elasticsearch/reference/current/aliases.html)
- [Bojie Li《深入理解 AI Agent：设计原理与工程实践》官方仓库](https://github.com/bojieli/ai-agent-book)
- [本文分析时固定的官方仓库提交](https://github.com/bojieli/ai-agent-book/tree/873a20ced1cbe6782be4ee1a7075fe60a025db7a)

本文对外部资料仅做架构思想转述，没有复制大段原文。Content was rephrased for compliance with licensing restrictions.
