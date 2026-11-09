# Main Agent + Subagent：当前运行与部署

本次交付切换了真实 `/chat` 与 `/chat/resume` 运行入口。状态是**核心代码已实现、离线验证通过、真实部署验收待完成**，不表示路线文档所有阶段已完成。

## 真实链路

```text
Java JWT 用户身份 → 服务认证 → RunService / MySQL 运行账本
→ Main Agent 每轮选择下一步动作
  ├─ answer：直接回复，不调用 Planner 或 Chat Subagent
  ├─ retrieve：knowledge 走共享 RAG；memory 召回当前用户记忆 → 结果与状态回到 Main
  ├─ delegate：校验只读 DAG → 依赖就绪且有并发名额即执行 → 全批结果回到 Main
  └─ write_draft：生成 → 来源校验 → 用户审批 / 修改 → 保存或放弃
→ answer / 草稿业务终端结果 → 引用与来源复核 → 消息与运行终态事务提交
```

主 Agent 的入口是 `main_agent.py`：`MainDecision` 是通过现有 DeepSeek/LangChain `function_calling` 结构化输出实现的受控动作协议。每轮模型直接分析输入，并输出完整回答或下一步执行请求，代码执行后将 `observations`、完整成功结果和剩余预算放入下一轮上下文；没有每次必经的第二个 LLM 分类器，也不要求先生成完整任务计划。普通问答通常一轮完成；单次查询通常是 `retrieve → answer` 两轮 Main 决策，检索内部仍有 Query Rewrite 等调用。Main 可在不同轮次交替检索和委派。

### 一次 Main 调用究竟输出什么

`action` 是本轮 Main 选定的动作，仅有 `answer/retrieve/delegate/write_draft`。Main 的分析在这次调用中直接完成，已删除顶层 `analyze`、`main_analyze` 节点及另调一次模型执行分析的路径。

- `answer`：同一次调用已经生成完整 `reply`，后端校验后交付，不再另调模型执行“回答任务”。
- `retrieve`：同一次调用生成查询参数和 `retrieval.target`，默认 `knowledge` 调用共享知识检索，`memory` 查询当前用户相关历史事件和决策；画像与有效约束已在请求开始加载，检索完成后再调用 Main 决定下一步。
- `delegate`：同一次调用生成本批次 `plan`、任务指令和 `depends_on`，只有 `plan.tasks` 的 `subagent` 指定 Search/Analysis 执行器，不另调 Planner。后端按 DAG 启动子代理，子代理各自执行；批次完成后再调用 Main。
- `write_draft`：同一次调用生成 `draft_request`，不指定 `subagent`；后端进入生成、来源校验、审批和保存子图，其中草稿生成仍需要模型调用。

如果后续任务需要复用 Main 已经做出的比较、提纲等实际产物，非 `answer` 响应可以同时携带 `artifacts`。每项包含唯一 `task_id`、产物说明 `instruction`、**已经生成的完整正文 `result`**、声明依赖 `depends_on` 和证据要求 `requires_evidence`。代码保存到 `task_results[task_id]`，标记 `actor=main/status=succeeded`，不再调用 LLM 执行这些产物。分析就是最终回复时直接放在 `reply`，不保存额外产物；内部思考不作为产物输出。

例如检索已经得到 `research`，下一轮 Main 可以在**同一次响应**中给出：

```json
{
  "action": "write_draft",
  "artifacts": [{
    "task_id": "comparison",
    "instruction": "比较检索资料",
    "result": "基于资料得出的完整比较结论 [research:1]",
    "depends_on": ["research"],
    "requires_evidence": true
  }],
  "draft_request": {
    "task_id": "draft",
    "instruction": "根据比较结论生成待审批的草稿",
    "depends_on": ["comparison"],
    "requires_evidence": true
  }
}
```

这里的 `comparison.result` 是完成的产物，`draft_request.instruction` 才是后端随后执行的写作请求。产物与请求整体校验通过才提交：ID 不可覆盖，产物只能依赖已有成功结果或同一列表前面的产物；证据由代码继承，模型不能传入来源或用户身份。引用错误在同一个 Main 决策上下文中最多修正一次，原执行请求和证据依赖不能改变。

### 任务、执行者和能力分离

模型只输出业务请求：`RetrievalRequest`、`DraftRequest` 与委派计划中的 `DelegatedTask`。`subagent` 仅出现在 `DelegatedTask`，值限定为 `search/analysis`；模型不能提交 `actor`、`capabilities`、可信用户身份或执行 token。

后端将请求编译为 `ExecutionTask(kind, actor, ...)`：Main 检索是 `search/main`，Main 已完成分析产物是 `analysis/main`，草稿流程是 `writing/main`；委派任务是 `search/subagent` 或 `analysis/subagent`。新结果记录 `kind+actor`，不再借 `subagent` 表示任务类型。前端事件 `role` 继续作为检索、分析、写作显示标签，不参与授权。

有效能力由 `app/security/capabilities.py` 的当前服务端政策计算，并与 checkpoint 中已保存的能力取交集；旧记录没有能力字段时仍执行当前政策。`allow_web` 是联网请求，`AGENT_WEB_SEARCH_ENABLED` 是服务端联网上限（默认 `true`）；设置为 `false` 后，即使模型或查询改写请求联网也不能调用网页检索。Main 与 Search Subagent 应用相同检索政策，Analysis/Writing 不获授检索工具，Skill 文本或注册的 MCP 工具不能扩大能力。保存还必须通过用户审批及运行归属、token、内容 hash 校验。

旧内部任务的 `subagent` 由受限 checkpoint 加载器转换成 `kind`，执行者由服务端调度路径确定；新版模型合同不接受旧 `task.subagent`。兼容读取保留已完成结果、草稿与审批版本，不修改身份或开启 MCP 执行。此兼容针对同一动态动作图的内部格式，不保证早期节点结构不同的阶段图可以恢复。完整边界与示例见 [任务、执行者与能力边界](../../learning/agent/22-task-execution-boundaries.md)。

### 调度与结果输入

显式记忆召回不增加顶层动作或分类 LLM。`RetrievalRequest.target` 经后端编译进入 `ExecutionTask.retrieval_target`；知识任务获得 `platform_read` 和获准的 `web_search`，记忆任务仅获得 `memory_read`，不能联网。旧请求/内部任务默认 knowledge，委派 Search 保持知识检索。

请求开始只读取结构化 `user_profile` 与当前用户/当前会话的 `active_constraints`，不再自动召回事件。Main 的 `memory_changes` 在同一次决策调用中提出明确用户要求的保存/替换/取消，后端事务与 run 幂等回执管理更新；`constraint_overrides` 仅在本轮忽略已有约束。后台提取只写 event，不能恢复旧偏好。

显式查询最多 3 条 event/decision 候选，ES 与 MySQL 校验当前用户、适用范围及有效状态。约束不进向量库。变更的索引操作持久化在回执，失败在显式召回时重试；未同步完成不能报告成功未命中。返回独立 memory_sources，不添加公开 citations。查询完成但未命中不消耗纠错；只读超时/连接失败仍最多重试一次。语义同义键归并、有效期、goal 和增量提取水位尚未实现。详见 [结构化记忆运行说明](../../agent/memory/23-structured-memory-runtime.md)。

`workflow` 不再是顶层动作类别，固定业务流程由 `write_draft` 进入审批子图。委派只允许 Search/Analysis 子代理，必须说明独立并行或上下文隔离的收益。复杂度不强制决定执行者；有依赖的复杂任务既可由 Main 多轮直接完成，也可委派一个只读 DAG。DAG 按依赖就绪调度，例如 A→C 与独立慢任务 B 并行时，A 完成就可启动 C；`stages` 只表示依赖层级供展示，不再构成整层屏障。

Main 读取成功任务的完整结果及完整引用，已取消每项正文 3000 字符和引用 excerpt 600 字符的前缀截断。整体上下文（含提示词、动作 schema 和修正消息）超出预算时明确停止，Checkpoint 中的结果仍完整保留；尚未实现自动压缩或按需加载超预算结果。产物与 Analysis/Writing 执行任务只继承声明成功依赖的证据，单任务依赖上下文最多 48000 字符，结果正文最多 16000 字符；最终回答可用 `answer_dependencies` 选择来源，留空表示全部成功任务。未声明的结果不进入子任务上下文。失败分支的依赖标记为 blocked，独立分支继续完成；结果按 Task ID 累积，不覆盖已有结果。一个委派批次在全部任务结束后回到 Main；内部任务完成后可立即启动已就绪的后继任务，但 Main 当前不会在批次未结束时追加任务。

`observations` 保存每次实际执行或产物提交的成功、证据不足、工具故障、依赖阻塞状态；`action_history` 保存外部动作请求、任务 ID、实际参数、产物 ID 和指纹。它们帮助模型判断下一步，具体重试上限仍由代码执行。重复检查针对外部执行参数，不禁止 Main 在新信息下再次分析。

检索服务是唯一 RAG 管线：Query Rewrite → FilterResolver → RRF → MySQL 当前公开正文 → Reranker → CitationBuilder → 获准的公开联网检索。主 Agent 与 Search Subagent 共享它，检索服务本身不生成答案；生成阶段没有工具权限。动态 MCP 工具不授予执行器，HTTP 热重载入口关闭。

默认每次运行最多 8 轮 Main 决策、总共 8 个 Task（包含 Main 产物、失败和 blocked）、3 个并发子代理、Main 上下文 96000 字符；单次委派计划最多 8 个任务，一次运行最多一篇终端草稿。配置见 `agent-runtime.env.example`，轮数最大可配置为 20、任务总数 32、并发 8。运行默认 300 秒，审批默认 24 小时；模型/任务调用另有局部超时。轮数限制不等于所有内部模型调用的数量限制。

Self-Correction 分层：

1. **局部契约修正**：Main 动作格式、答案或产物引用最多修正一次；引用修正保留原动作、执行参数和证据依赖，只修正文。子代理分析、搜索摘要、草稿的无效引用最多基于原证据重新生成一次，不重新检索，不消耗策略恢复次数。
2. **Main 策略恢复**：证据不足时允许改变一次查询或方法；只读超时或连接故障 `tool_error` 允许原参数重试一次，这两类恢复共享一次预算。可复用成功任务，也可说明不足；再次失败时停止。重复动作指纹排除任务自身 ID，同一成功或证据不足的搜索更换 ID 或执行者仍不能绕过拦截。指纹仅检测相同参数，不宣称识别所有语义等价改写。
3. **确定性边界**：身份、来源发布状态/Hash、取消/执行 token、旧审批版本与保存错误不交给模型软重试。草稿保存或用户放弃后直接交付业务结果，不再调用模型决定动作。旧全局 Reflector 不在真实入口执行。

当前门禁覆盖结果存在性、依赖成功、引用编号、来源发布状态与内容 Hash，**不能据此宣称所有事实已得到语义忠实度验证**。委派批次在节点结束时提交其完整结果到 Checkpoint；当前没有逐个子任务的持久恢复队列，进程崩溃时不保证保留批次内已完成但尚未提交的只读结果。审批的生成、暂停和保存仍由独立子图节点持久化。

## 身份、状态和保存边界

- Java 的公开接口沿用 JWT，Python 通过 `X-Agent-Key` 验证调用服务，`X-Agent-User` 由 Java 登录身份构造。请求体用户必须匹配可信身份。
- 配置相同的随机 `AGENT_SERVICE_KEY`（至少 32 字节），缺失时拒绝运行。默认地址用于同机开发；跨主机部署配置 HTTPS 或受保护的服务网络，不把服务凭据交给浏览器。
- 当前业务文章只有“已发布且未删除”的公共范围，未新增关注者、项目或共享权限。
- `agent_run` 保存运行状态、deadline、执行 token、请求幂等键和审批 Hash。数据库生成列唯一约束保证同会话最多一个非终态运行。过期执行被状态和 token 复核隔离，Checkpoint 按 `run_id` 独立。
- `agent_run_event` 保存节点开始、结束、中断、失败与耗时；不存用户正文、工具参数或证据原文。当前未实现完整成本看板和评测平台。
- `request_id` 相同且输入相同的完成请求可返回原结果；输入不同返回 409。审批必须携带 `run_id/draft_hash`，重复、过期或旧版本审批拒绝。会话历史会重新展示未过期的待审批预览。
- 保存路径是 `Generate → Approve → SaveDraftNode → Java /internal/agent/drafts`。Python 渲染 Markdown，Java 白名单清洗并按 HTML `content_type=1/status=0` 保存。Java 在同一 MySQL 事务中锁会话与运行，写草稿和已提交 ID；Python 不再从真实入口直写文章表。
- 取消先取得事务锁，则后续不能保存；草稿先提交，则取消如实返回 `draft_saved`。重复保存返回既有 ID，不覆盖编辑内容。Java/Python 草稿 Hash 使用 UTF-8 字节长度前缀，与审批展示的内容绑定。
- Java 和 Python 当前共用现有 MySQL：`agent_run` 是双方协调事务的载体。若未来拆成不同数据库，应重新设计保存协议和 Outbox，不能照搬当前锁规则。
- 平台 RAG 以 HTML DOM 结构分块，BM25/KNN 都查询 `article_vectors` 并以版本化 chunk_id 做 RRF。MySQL 回查校验公开状态、正文 Hash 与筛选元数据，保留块正文；生成审批或交付前再次校验来源 Hash。每篇索引写入有共享命名锁，完成 Bulk 后才清理旧块；完整 Outbox/原子发布仍未实现。旧文章需要显式启用 Java `rag.reindex.enabled=true` 重建，完成后关闭。详见 `docs/learning/agent/24-html-chunk-rag.md`。

## 前端流式交互

SSE 实时传输公开执行状态：`__AGENT_EVENT__` 包含版本 1 的 `commentary/plan/activity/status`，展示当前动作、增量任务计划、实际检索/重排/引用校验与子任务状态。Main 活动按轮次生成稳定 ID，避免下一轮覆盖上一轮记录；任务按 Task ID 就地更新，委派任务可同时显示运行。工作结束后默认折叠，仍可展开查看。事件只描述可观察的工作，不转发模型思考、提示词、用户全文或检索正文。

答案在最终引用/来源校验及运行结果提交后，通过 `__ANSWER__` 的 `start/delta/end` 分段发送，序号从 0 开始，每段最多 512 个字符；保留 `__REPLY__` 作为完整结果兼容及重放替换。**这是已校验答案的分段传输，尚不是模型生成时逐 token 展示**，没有人为打字延迟。短答案可能一次显示完成。Java/Python 设置不缓存、禁止代理缓冲的响应头，生产反向代理仍需实际验证。

`__INTERRUPTED__` 单独渲染草稿确认卡片，支持保存、放弃和提出修改意见；修改后的内容需要重新确认。聊天与恢复共用 SSE 解码和事件处理，支持跨网络分片、UTF-8、CRLF/多行 data，分段缺失或连接未收到 `[DONE]` 时显示错误。当前活动记录只保留在当前页面内，刷新后的历史恢复回复、引用和未过期待审批草稿；未实现持久事件回放、断线自动续接和历史活动时间线，路线中完整事件信封仍是后续工作。

## 部署顺序

1. 暂停新 Agent 请求，处理旧未完成审批并备份 MySQL。旧 `conv_*` 和此前阶段图的 `run_*` Checkpoint 不保证按新图恢复；本次删除了阶段屏障节点并改变 Main 状态协议。升级前应结束旧执行，在隔离环境验证历史 checkpoint；不能因为审批节点同名就假设兼容。已有聊天历史和已保存草稿保留。
2. 安装 `requirements.txt`，Java、Python、前端配套更新。配置示例见 `agent-runtime.env.example`；Java 通过环境变量读取同一个服务 key，Python 读取环境变量或 `.env`。
3. 在 `python-agent` 运行 `python -m app.migrate`，显式应用 `001_message_metadata.sql`、`002_agent_runs.sql` 和 `003_structured_memory.sql`。迁移有数据库锁与 checksum，启动只检查结构，不自动执行 DDL。**本次未连接真实数据库运行迁移。**
4. 确认 Java/Python 指向同一个业务 MySQL；检查 Python Redis Stack 支持 Checkpoint，ES、模型和联网检索配置齐全。按实际端口配置 `JAVA_AGENT_URL` 和 Java `agent.python-url`。
5. 启动服务，完成下述真实验收，再恢复请求。调用取消/运行查询应保留返回的草稿提交状态；不要把浏览器断开解释为业务保存回滚。

## 验证命令

```powershell
# python-agent
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check

# 项目根目录
mvn -o '-Dtest=AgentProxyTests,AgentBoundaryTests,DocumentChunkServiceTests,ArticleChunkIndexTests,ArticleIndexPublisherTests' test

# frontend
npm run test:agent-stream
npm run build
```

离线用例使用真实 LangGraph InMemorySaver，模拟外部数据库、模型和 HTTP 服务。当前 87 个 Python 用例通过，覆盖同次调用完成 Main 分析并消费产物、产物证据/身份/依赖边界、完整结果输入、超预算保留结果、限次原参数故障重试、动作结果回到 Main、部分成功复用、依赖就绪调度、取消、共享 RAG、最终来源复核、审批恢复及流式活动。本轮 6 个前端协议用例、`pip check` 通过；此前 8 个 Java 代理/边界用例、Java 编译、前端构建与离线浏览器交互已验证。本轮没有修改 Java 或前端组件，未重复这些构建和浏览器检查。离线验证不会证明真实 MySQL 隔离级别、Redis Stack 恢复、网络代理或实际模型质量。

## 发布前真实验收与回滚

- 两个 Python 实例同时提交同会话请求：仅一个进入执行；同时 resume：仅一个被接受；取消与 Java 保存竞争：只出现取消或已提交草稿。
- Java 保存已提交但返回丢失：通过相同 request_id 重放或 `/api/agent/runs/{runId}` 查询恢复原草稿 ID，文章与 assistant 消息不能重复。
- Python/Redis Stack 重启后恢复已预览草稿，标题、正文、Hash 不变；改稿后旧审批不能保存。
- 非本人的图片路径、会话、运行、历史和草稿请求被拒绝；已下架或更新文章不能通过来源复核。
- 标注真实检索/创作样本，评估忠实度、引用准确率、任务覆盖、成本和延迟，再确认生产门槛。
- 使用实际模型验证普通聊天直接 `answer`，查询 `retrieve → answer`，连续任务根据实际结果选择 `retrieve/delegate/write_draft`，分析在当前调用内直接完成，复用产物通过 `artifacts` 输出。记录误委派率、轮数、调用次数、延迟和成本；离线控制输出不能证明实际模型的决策准确率。

回滚时先停止新执行并处理待审批，保留新增表、消息字段和已保存文章；回滚整个 Java/Python/前端配套版本。不要把新 `run_*` Checkpoint 交给旧图，不删除已提交草稿。当前 Memory V1 后处理仍是进程内可选任务，可靠记忆投递、Memory V2、文章索引 Outbox/版本发布和完整语义 EvidenceGate 仍需后续实施。
