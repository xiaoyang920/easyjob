# Main Agent 的任务、执行者与能力边界

本文说明当前改造采用的输出合同与执行边界。解决的问题是：此前 `PlannedTask.subagent` 同时表示任务类型、执行者和部分工具权限，导致 Main 自己检索、已完成的分析产物、固定草稿流程也被标记成子代理。

改造后，只有 **Main 委派的待执行任务**需要指定 `subagent`。后端分别记录“做什么”“谁执行”“可以调用什么”，它们不再共用一个字段。

## 1. Main 决定动作，后端建立执行任务

Main 每轮分析用户问题、已有结果和执行状态，输出一个合法动作。`MainDecision` 的执行请求字段为 `retrieval`、`draft_request`、`plan`；没有通用的 `task` 字段，也不接受模型指定可信身份、执行者或有效能力。

| action | 模型输出的主要字段 | 后端执行路径 |
| --- | --- | --- |
| `answer` | `reply`、回答所用的成功结果依赖 | 校验引用后返回答案 |
| `retrieve` | `retrieval.target`、`instruction` 等 | `knowledge` 调用知识检索；`memory` 调用当前用户记忆检索 |
| `write_draft` | `draft_request` | 生成、来源校验、用户审批、保存或放弃 |
| `delegate` | `plan.tasks`、`delegation_reason` | 按依赖就绪调度只读子代理 |

`answer` 不混入待执行请求；其他动作也不能同时输出最终回复。Main 在本轮已经完成、后续需要复用的分析仍通过 `artifacts` 输出，不引入额外的顶层 `analyze` 动作。

### 知识与记忆共享 retrieve 动作

```json
{
  "action": "retrieve",
  "retrieval": {
    "target": "memory",
    "task_id": "history",
    "instruction": "查找此前放弃阶段屏障的原因"
  }
}
```

`target` 默认是 `knowledge`，兼容已有知识检索请求。Main 在正常决策调用中选择目标，不增加必经分类模型，也不增加 `recall_memory` 动作。后端将目标写入 `ExecutionTask.retrieval_target`，实际执行从执行任务读取目标，不从模型输出重新猜测。只有 Main 的显式检索支持 `memory`；当前委派 Search 仍只检索知识。

记忆分支使用 `MemoryService.recall_details`：最多 3 个 event/decision 候选，ES 按可信用户和范围前置过滤，MySQL 复核归属、scope、active状态及当前正文，恢复候选顺序。画像及有效约束改为请求开始独立读取，不再自动召回事件。模型的检索请求不能提供 user_id、数据库过滤器、作用域或 top_k。显式查询使用严格错误路径，索引同步未完成或服务不可用不会伪装成未命中。

记忆结果包含 `memory_sources`、`memory_found` 和 `memory_match_count`，不产生文章 citations/cards。空查询结果也表示该操作成功完成，不消耗证据纠错预算；Main 能看见未命中。画像不再包含在显式检索结果中，也不能作为某次历史决策的证明。历史记忆可能含旧编号，因此原文作为数据保留，但不能转成公开引用；有据写作依赖仍需真正的文章/网页证据。

目前已落地用户/会话范围的 constraint/decision/event、有效状态、明确替换/取消、独立 State、run幂等回执及变更索引重试，不引入博客业务没有的项目实体。goal、有效期、同义语义键归并和增量提取水位仍待实现。历史候选不保证用户确认，当前用户指示优先。详见 [结构化记忆运行说明](../../agent/memory/23-structured-memory-runtime.md)。

### 草稿请求示例

```json
{
  "action": "write_draft",
  "draft_request": {
    "task_id": "rag_draft",
    "instruction": "根据已经核验的资料写一篇 RAG 实践文章，生成后交给用户确认保存。",
    "depends_on": ["rag_sources"],
    "requires_evidence": true,
    "required_skills": []
  }
}
```

`DraftRequest` 描述写作要求及证据依赖，不包含 `subagent`、`actor`、`capabilities`。`write_draft` 进入固定业务子图，不需要 Main 再选择 Writing Subagent，也不会因生成草稿而自动获得保存权限。

### 委派请求示例

```json
{
  "action": "delegate",
  "delegation_reason": "两项检索可以独立执行，随后在隔离上下文中比较证据。",
  "plan": {
    "tasks": [
      {
        "task_id": "rag_search",
        "subagent": "search",
        "instruction": "检索平台上关于 RAG 检索质量的实践资料。",
        "allow_web": false
      },
      {
        "task_id": "rag_compare",
        "subagent": "analysis",
        "instruction": "比较检索结果中的方法、适用条件及资料局限。",
        "depends_on": ["rag_search"],
        "requires_evidence": true
      }
    ]
  }
}
```

模型合同中的类名为 `DelegatedTask`，仅允许 `subagent="search"` 或 `subagent="analysis"`。这个字段用于选择专业执行器；Writing 和 Chat 不属于当前委派计划的执行器。依赖无环且已就绪的任务才会运行，依赖失败的任务不会消费失败结果。`stages` 仍可展示依赖层级，执行不等待整层屏障。

## 2. 执行任务和结果不伪造子代理

模型请求通过校验后，由后端转换为 `ExecutionTask`：

| 场景 | kind：任务类型 | actor：执行者 |
| --- | --- | --- |
| Main 直接检索 | `search` | `main` |
| Main 显式记忆召回 | `search`，`retrieval_target=memory` | `main` |
| Main 已完成的分析产物 | `analysis` | `main` |
| Main 进入草稿业务流程 | `writing` | `main` |
| 委派 Search | `search` | `subagent` |
| 委派 Analysis | `analysis` | `subagent` |

`kind` 决定输入、证据要求及对应执行服务；`actor` 记录执行归属。二者由后端根据已验证的动作构造，模型不能把直接动作改标为子代理，或自报 `actor="main"` 来扩大权限。

任务结果记录 `task_id`、`kind`、`actor`、状态、正文、引用等信息，不再包含 `subagent`。Main 的成功结果上下文、执行状态和动作历史继续累积，不能覆盖已有任务 ID。重复策略检测也不能因更换任务 ID 或执行者而被绕过。

前端事件中的 `role` 保留用于既有界面显示，例如检索、分析、写作标签。它是展示字段，不参与执行授权；活动记录同时使用 `actor` 区分 Main 与子代理。这样无需把界面的标签兼容性当作后端权限设计的一部分。

## 3. 能力由服务端授予

`app/security/capabilities.py` 根据服务端政策和已验证的任务类型生成允许能力，并与 checkpoint 保存的已有能力取交集。持久化能力可以收窄授权，不能突破当前政策；旧状态没有能力字段时仍按当前政策校验。模型请求不是授权结果，Prompt、Skill 正文、专业角色名称也不具有授予能力的效力。

- Main 直接检索与 Search Subagent 使用同一检索能力政策，不能因为换成子代理就获得更大的资料范围。
- `search/knowledge` 只授予 `platform_read` 和获准的 `web_search`；`search/memory` 只授予 `memory_read`。知识执行器不能查记忆，记忆执行器不能进入知识服务，即使 state 中伪造更大能力列表也不能扩大有效能力。数据归属由检索服务继续校验。
- `allow_web` 仅表示请求联网。`AGENT_WEB_SEARCH_ENABLED` 是服务端联网上限（默认 `true`）；关闭时，即使 Main 请求联网、查询改写建议联网，也不能执行公开网页检索。
- Analysis 与 Writing 消费声明依赖中的资料，不自行检索。生成阶段不因 Skill 要求而绑定额外工具。
- 工具注册中心发现一个本地工具或 MCP 工具，不等于当前任务获准执行它。本次改造不开放动态 MCP 工具执行，也不通过角色名取得全部工具。
- 平台检索仍只返回已发布且未删除的公共文章，并通过 MySQL 回查当前正文；记忆召回仍重新检查用户归属。执行者标签不改变数据可见范围。

`requires_evidence` 是证据质量约束，并非资料访问权限。有据分析或写作必须声明成功依赖并获得可信引用；模型不能自行构造引用对象来满足这一约束。

## 4. 保存是独立的业务授权边界

生成草稿与保存草稿是不同动作。固定写作子图先生成并校验来源，再通过 checkpoint/interrupt 等待用户决定；批准后保存，拒绝不保存，修改后重新生成并等待再次批准。

保存仍检查可信运行的用户与会话归属、运行状态和期限、执行 token、用户已审批的内容 hash，并保留幂等性。恢复时使用服务端重新认领的执行 token，模型不能修改这些身份或授权信息。

因此，“草稿流程的 actor 是 Main”不代表 Main 可以跳过审批写入。保存权限由业务状态及用户批准决定，不由 `subagent="writing"`、`kind="writing"` 或提示词中的“请保存”授予。

## 5. 已有运行和 checkpoint 的格式兼容

同一动态动作图的已有服务器状态可能保存旧的 `plan/current_task/task_results` 格式，其中 `subagent` 曾被用于表示任务类型。服务器读取这些历史内部状态时进行受限规范化，转换为新的执行任务或结果视图，并根据运行上下文恢复执行者。已完成结果不会为修改标签而覆盖原有不可变记录；历史结果的展示视图可使用兼容默认标签，这不参与授权。本兼容不保证更早、节点结构不同的扁平图或阶段图能够恢复。

兼容处理遵守以下边界：

1. 只兼容已有内部运行和 checkpoint 数据。新版模型请求仍严格遵守新的 `MainDecision` 合同，不能继续提交 `task.subagent="writing"`，也不能借旧格式提交身份或能力字段。
2. 旧字段映射只恢复任务语义和执行归属，不恢复或扩大旧权限。实际执行时仍按当前服务端政策计算能力；当前已关闭的联网不能被旧 `allow_web=true` 打开。
3. 保留原任务 ID、已完成结果、依赖、引用、草稿内容和审批版本，避免格式迁移导致已成功任务重跑或草稿重复生成、保存。
4. 归属、执行 token、审批 hash 和业务状态继续由原有可信运行边界校验。格式兼容不能更改用户身份，也不能绕过已过期或被取消的运行。
5. 无法可靠恢复的待执行任务或授权上下文应校验失败，不能通过赋予更多能力继续执行。历史已完成结果的显示标签兼容不构成执行授权。

这种处理兼容的是服务器已持有的内部格式，而不是给模型新增一套长期可用的旧输出接口。

## 6. 回归验证重点

- 非委派模型请求拒绝 `subagent`、`actor`、`capabilities`；委派仅接受 Search/Analysis。
- 直接检索和委派检索应用相同服务端政策；禁联网时任何请求与改写都不能调用网页检索。
- Analysis、Writing、Skill 和 MCP 元数据不能扩大工具能力，草稿批准之前没有保存操作。
- 已有内部状态规范化后，结果正确记录 `kind/actor`，前端活动标签继续正常显示。
- 替换执行者或任务 ID 不能绕过重复策略检测；任务依赖、引用校验及恢复预算继续有效。
- 归属校验、过期 token、拒绝审批、修改后二次审批、保存幂等性与取消执行的既有用例继续通过。
