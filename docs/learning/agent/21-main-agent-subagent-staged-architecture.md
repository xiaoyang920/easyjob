# Main Agent + Subagent 阶段化执行架构

> 文档性质：Agent 架构演进方案与面试说明。  
> 当前状态（2026-10-01）：**Main 动态动作循环与按需 Subagent 已接入真实入口，离线验证通过，真实部署验收待完成**。入口见 `python-agent/app/graph/builder.py`，逐轮决策见 `main_agent.py`，动作执行与依赖就绪调度见 `action_runtime.py`，依赖校验见 `staged_plan.py`，隔离、引用和 fencing 见 `staged_runtime.py`；部署与已知缺口见 `docs/archive/setup/STAGED_SETUP.md`。当前任务合同与权限边界以 [任务、执行者与能力边界](22-task-execution-boundaries.md) 为准：`subagent` 仅用于委派请求，草稿使用 `draft_request`，内部任务与结果使用 `kind+actor`，有效能力由服务端政策生成。后文旧架构章节作为历史设计，不能当作当前入口状态，也不能照用旧类名、角色授权或阶段屏障。  
> 目标状态：Main Agent 默认执行；需要独立并行工作或专业上下文隔离时，才委派 Subagent。
>
> 本文档除阶段化调度外，还回答三个高频设计问题：
> - 第十四节：RAG 由谁调用，以及为什么检索入口必须唯一。
> - 第十五节：主子 Agent 之间的文档权限模型与上下文分层策略。
> - 第十六节：重试为什么可能返回相同结果，以及重规划生效的必要条件。
>
> 第十七节给出对应的面试口径，并在末尾如实列出尚未打通的实现缺口。

## 当前执行规则（优先于后文早期设计）

Main 每轮在一次模型调用中直接分析并输出 `MainDecision`：生成完整回答，或选择下一步外部动作及其参数。分析不再是顶层 `analyze` 动作，也不另调模型执行 Main 分析；需要后续复用时，在同一次响应的 `artifacts` 中给出已完成的完整正文，代码保存为 `actor=main` 的结果供后续任务声明依赖。执行后的状态和完整结果进入下一轮上下文，Main 根据新信息继续选择；普通聊天可以第一轮结束，无需预先拆解全部请求。现有 DeepSeek/LangChain 以 `function_calling` 结构化输出受控动作，不增加每次必经的 LLM 分类器。具体字段与单次调用示例见 `docs/archive/setup/STAGED_SETUP.md`。

| 动作 | 实际执行 | 适用场景 |
| --- | --- | --- |
| `answer` | Main 完整回复 → 最终校验 | 普通问答、概念解释、简单创作 |
| `retrieve` | 共享检索 → 结果与状态回到 Main | 直接查询资料 |
| `delegate` | 校验只读 DAG → 依赖就绪即执行 → 批次结果回到 Main | 独立并行研究或专业上下文隔离 |
| `write_draft` | 生成 → 来源校验 → 审批/修改 → 保存或放弃 | 固定草稿业务流程 |

`workflow` 不再是互斥顶层类别，而是草稿审批等代码固定的业务约束。直接执行与委派可以在同一请求的不同轮次组合；委派必须给出收益理由。Kahn 校验仍检查依赖，但执行采用依赖就绪调度：A→C 与独立慢任务 B 同时进行时，A 完成即可启动 C，无需等待 B。子代理只支持只读 Search/Analysis，Writing 由 Main 进入独立审批子图，保存或放弃后不再调用模型决定动作。

Self-Correction 相应分层：动作格式、答案/产物引用错误最多在原上下文/原证据内修正一次，引用修正不得改变动作、执行参数或证据依赖。证据不足时允许改变一次策略；只读超时或连接故障允许原参数重试一次，两者共享一次恢复预算，可复用成功 Task；成功或证据不足的相同动作、再次失败或预算耗尽停止。权限、来源 Hash 变化、取消/执行 token、审批版本、保存失败保持确定性边界，不让模型软重试。旧全局 Reflector 与阶段 Barrier 已退出真实入口。

默认 8 轮、全运行 8 个 Task（包括 Main 产物）、3 个并发子代理；Main 控制上下文限制 96000 字符，Task 依赖上下文 48000 字符。Main 读取完整成功结果和引用，不按每项固定前缀截断；整体超预算则明确停止，结果仍完整保留在状态中。`task_results` 按 ID 累积，`observations` 保存执行状态，`action_history` 包含实际任务参数；重复检查不限制 Main 根据新资料继续分析。委派批次结束才统一提交结果到 Checkpoint，尚无逐子任务持久恢复。具体限制与离线验证范围见部署文档。

RAG 的唯一入口是**共享检索服务**，主 Agent 和 Search Subagent 都可以调用同一条已验证管线，不开放旁路裸搜索。Main 不负责 embedding、RRF 和重排算法。后文“Main 只能规划”“站内检索必须经过 Search Subagent”以及面试口径中的相同说法，已由本节替代。其他尚未实现的目标能力仍以部署说明和统一路线第18节为准。

当前前端实时展示公开处理说明、任务计划与实际活动状态，委派任务显示各自进度，完成后记录可折叠；草稿以单独确认卡片展示。最终答案在校验及提交后分段传输，保留 `__REPLY__` 完整结果；目前没有模型生成时的逐 token 输出、持久事件回放或断线自动续接。第十三节仍包含更完整的目标协议，不能据此宣称全部实现。

## 一、问题背景

以下“一、问题背景”至后续早期方案章节保留架构演进背景。文中的“当前”描述撰写时的历史基线；与上方当前执行规则或新任务边界文档冲突时，以当前实现说明为准。

EasyJob 当前使用 Python FastAPI + LangGraph 作为 Agent 运行时，主要节点包括：

- `planner`：理解用户意图并选择 Worker。
- `dispatcher`：通过 LangGraph `Send` API 并行调度 Worker。
- `search_worker`：站内文章与联网信息检索。
- `analysis_worker`：分析、对比和总结。
- `writing_worker`：内容创作与草稿生成。
- `chat_worker`：普通对话与技术问答。
- `reflector`：检查结果并决定是否重试。
- `synthesizer`：汇总结果并流式生成最终回答。

当前主要代码：

- `python-agent/app/graph/nodes/planner.py`
- `python-agent/app/graph/nodes/dispatcher.py`
- `python-agent/app/graph/state.py`
- `python-agent/app/graph/builder.py`

## 二、当前架构

```text
用户请求
   ↓
Planner
   ↓ active_workers
Dispatcher
   ├─ SearchWorker
   ├─ AnalysisWorker
   ├─ WritingWorker
   └─ ChatWorker
   ↓
Reflector
   ↓
Synthesizer
   ↓
最终回答
```
### 2.1 Planner 当前输出

当前 `PlannerOutput` 是扁平结构：

```python
class PlannerOutput(BaseModel):
    active_workers: list[str]
    task_descriptions: dict[str, str]
    is_degraded: bool = False
    required_skills: list[str] = []
```

例如用户要求“搜索 Spring Boot 最新资料，进行分析并写成文章”，Planner 可能输出：

```json
{
  "active_workers": ["search", "analysis", "writing"],
  "task_descriptions": {
    "search": "搜索相关资料",
    "analysis": "分析相关资料",
    "writing": "根据资料生成文章"
  }
}
```

### 2.2 Dispatcher 当前行为

`dispatcher_node()` 遍历 `active_workers`，为每个 Worker 返回一个 `Send`：

```python
for worker in active_workers:
    sends.append(Send("对应的_worker节点", state))
```

LangGraph 会把这些 Worker 放进同一个 superstep 并行执行。所有 Worker 获取的是 Dispatcher 调度时的同一份 State 快照。

### 2.3 当前架构的优势

- 独立任务可以并行执行，降低总延迟。
- Worker 职责和 Prompt 相互隔离。
- `worker_results`、`article_cards`、`citations` 可通过 reducer 合并。
- 简单问题可以只选择一个 Worker，执行链路较短。

## 三、当前架构的核心限制

### 3.1 同阶段 Worker 无法读取彼此的执行结果

并行 Worker 从同一个 State 快照开始执行。某个 Worker 返回的局部 State 更新，要等当前 superstep 全部结束后才会通过 reducer 合并。

因此：

- `AnalysisWorker` 无法在运行过程中读取同批 `SearchWorker` 的结果。
- `WritingWorker` 无法在运行过程中读取同批 `AnalysisWorker` 的结论。
- `SearchWorker`、`AnalysisWorker`、`WritingWorker` 同时运行，不等于真正完成了“搜索 → 分析 → 写作”的协作链。

### 3.2 reducer 只能合并结果，不能解决执行依赖

当前 State 使用以下 reducer：

```python
worker_results: Annotated[list[dict], add]
article_cards: Annotated[list[dict], add]
citations: Annotated[list[dict], add]
```

它们可以在并行任务结束后合并列表，但无法让仍在运行的 Worker 看见其他 Worker 的中间结果。这是并行 superstep 的正确隔离语义，不是 reducer 的缺陷。

### 3.3 典型错误场景

```text
用户：搜索最新的 Spring Boot 特性，和站内文章进行对比，再帮我写一篇总结。

当前执行：
SearchWorker   ──────┐
AnalysisWorker ─────┼─ 同时执行
WritingWorker  ─────┘
```

此时 AnalysisWorker 没有真实搜索结果可分析，WritingWorker 也没有搜索证据和分析结论，只能根据用户原始问题独立生成内容。

正确的数据依赖应该是：

```text
搜索结果 → 分析结论 → 写作输入
```

## 四、目标架构：Main Agent + Subagent

目标架构不是简单地把 Worker 改名为 Subagent，而是重新划分控制职责：

- 现有专业 Worker 演进为 Subagent。
- Planner、阶段调度、结果合并、反思和最终汇总共同构成 Main Agent 的控制逻辑。
- Main Agent 管理计划、状态、阶段、预算、重试和最终回答。
- Subagent 只执行职责单一的专业任务。

```text
用户请求
   ↓
Main Agent
   ├─ 理解意图
   ├─ 生成阶段计划
   ├─ 调度 Subagent
   ├─ 合并阶段结果
   ├─ 判断是否重新规划
   └─ 生成最终回答
        │
        ├─ Search Subagent    （站内 RAG 与联网检索，靠 instruction 区分任务）
        ├─ Analysis Subagent
        ├─ Writing Subagent
        └─ Chat Subagent
```

Subagent 白名单以第 9.1 节的 `SubagentName` 为准，当前只有上述四个。`search` 是一个 Subagent，而不是 PlatformSearch 与 WebSearch 两个：两类检索共用同一套查询改写、混合召回和重排链路，只有检索范围不同，通过 Main Agent 下发的 `instruction` 和 Subagent 内部的 `search_mode` 区分。只有当两者的工具白名单和输出 Schema 出现实质分化时，才值得拆成两个 Subagent。

Memory 目前不是 Subagent。会话摘要与长期记忆由 `app/services/conversation.py` 和 `app/services/memory.py` 在请求前后作为服务调用，不参与阶段调度。

长期记忆 V2 的目标时序是“Main Agent 规划前召回 + 计划生成后按 Task 精准召回”，并通过独立 `memory_context` 注入，而不是把全部记忆广播给所有 Subagent。完整的数据模型、`user/project` 作用域、ES KNN 前置过滤、MySQL 复核和冲突替代方案见 [`22-long-term-memory-v2.md`](../../agent/memory/22-long-term-memory-v2.md)。该方案尚未实现。

## 五、阶段化执行模型

### 5.1 核心原则

- 同一阶段中的任务必须相互独立，可以并行执行。
- 下一阶段必须等待上一阶段全部完成。
- 下一阶段只能读取已经完成的前序阶段结果。
- 同阶段 Subagent 不互相通信，也不轮询彼此状态。
- 阶段之间通过明确的数据屏障 Stage Barrier 隔离。

### 5.2 示例执行流程

```text
Main Agent 生成计划
   ↓
Stage 0：资料收集
   ├─ Task platform_search → search Subagent（站内 RAG）
   └─ Task web_search      → search Subagent（联网检索）
   ↓
Stage Barrier：校验并合并 Stage 0 结果
   ↓
Stage 1：内容分析
   └─ Task compare → analysis Subagent
   ↓
Stage Barrier：校验分析结论
   ↓
Stage 2：内容写作
   └─ Task draft → writing Subagent
   ↓
PrepareResults → Reflector → Synthesizer
   ↓
最终回答
```

注意 Stage 0 的两个 Task 指向同一个 `search` Subagent，是两次独立调用而不是两个 Subagent 类型。`stage_id` 由 `build_execution_stages()` 生成，从 `stage_0` 开始编号。

这样既保留独立检索任务的并行优势，又保证分析和写作获得真实的前序结果。

## 六、Planner 的阶段化输出

### 6.1 建议的数据结构

```json
{
  "stages": [
    {
      "stageId": "collect",
      "description": "收集站内和外部资料",
      "tasks": [
        {
          "taskId": "platform_search",
          "subagent": "search",
          "instruction": "搜索平台内 Spring Boot 相关文章",
          "inputFrom": []
        },
        {
          "taskId": "web_search",
          "subagent": "search",
          "instruction": "搜索 Spring Boot 最新版本特性",
          "inputFrom": []
        }
      ]
    },
    {
      "stageId": "analyze",
      "description": "对比站内文章与最新资料",
      "tasks": [
        {
          "taskId": "compare",
          "subagent": "analysis",
          "instruction": "对比分析站内文章对最新特性的覆盖情况",
          "inputFrom": ["platform_search", "web_search"]
        }
      ]
    },
    {
      "stageId": "write",
      "description": "生成技术总结",
      "tasks": [
        {
          "taskId": "draft",
          "subagent": "writing",
          "instruction": "根据资料和分析结论撰写技术总结",
          "inputFrom": ["platform_search", "web_search", "compare"]
        }
      ]
    }
  ]
}
```

### 6.2 Pydantic 模型示例

```python
class SubagentTask(BaseModel):
    task_id: str
    subagent: str
    instruction: str
    input_from: list[str] = Field(default_factory=list)

class ExecutionStage(BaseModel):
    stage_id: str
    description: str
    tasks: list[SubagentTask]

class StagedPlannerOutput(BaseModel):
    stages: list[ExecutionStage]
    required_skills: list[str] = Field(default_factory=list)
```

### 6.3 Planner 输出不能直接信任

即使使用结构化输出，后端仍需校验：

- `stageId` 和 `taskId` 必须唯一。
- Stage 和 Task 不能为空。
- Subagent 必须在白名单中。
- `inputFrom` 只能引用前序阶段已经定义的 Task。
- 不允许引用同阶段或后续阶段 Task。
- 阶段数、单阶段任务数和总任务数不能超过上限。
- 高风险任务必须插入 HITL 审批阶段。

## 七、更加稳健的依赖规划方式

让 Planner 直接输出 Stage 比较直观，但模型可能把有依赖的任务错误放进同一阶段。更加稳健的方式是：

1. Planner 输出 Task 和 `dependsOn`。
2. 后端验证任务与依赖。
3. 后端执行拓扑排序并检测环。
4. 后端根据拓扑层级自动生成并行 Stage。

例如 Planner 输出：

```json
{
  "tasks": [
    {"taskId": "platform_search", "subagent": "search", "dependsOn": []},
    {"taskId": "web_search", "subagent": "search", "dependsOn": []},
    {"taskId": "compare", "subagent": "analysis", "dependsOn": ["platform_search", "web_search"]},
    {"taskId": "draft", "subagent": "writing", "dependsOn": ["compare"]}
  ]
}
```

由代码生成：

```text
Stage 1 = platform_search + web_search
Stage 2 = compare
Stage 3 = draft
```

这种方案把自然语言任务拆解交给模型，把依赖校验、环检测和阶段划分交给确定性代码，更适合生产环境。
## 八、Superstep 与 Barrier

### 8.1 什么是 Superstep

LangGraph 的执行模型借鉴了 Pregel/BSP（Bulk Synchronous Parallel，整体同步并行）思想。一次图运行不是让所有节点随意读写同一份可变 State，而是按一个个 **superstep** 推进。

一个 superstep 可以理解为“一轮并行计算”：

1. 运行时确定这一轮需要执行的所有节点。
2. 这些节点读取本轮开始时可见的 State。
3. 节点可以并行执行并产生局部更新。
4. 本轮所有节点结束后，LangGraph 使用 reducer 合并更新。
5. 合并后的 State 只对下一个 superstep 可见。

例如当前 Dispatcher 同时发送三个 Worker：

```text
Superstep N：
  SearchWorker   读取 State(N)
  AnalysisWorker 读取 State(N)
  WritingWorker  读取 State(N)

本轮结束：
  reducer 合并三个 Worker 的更新，得到 State(N+1)
```

因此 AnalysisWorker 在 Superstep N 中不能读取 SearchWorker 同一轮刚产生的结果。即使 SearchWorker 实际运行得更快，它的更新也要在 superstep 边界合并后才可见。

### 8.2 什么是 Barrier

Barrier 是“并行任务汇合屏障”。它保证下一阶段不会在当前阶段仍有任务运行时提前开始。

```text
Task A ─────┐
Task B ─────┼── Barrier ── 下一阶段
Task C ─────┘
```

Barrier 不是 Python 的 `asyncio.Barrier`，也不是在节点里写死循环等待。它是图结构中的一个 **fan-in/reduce 节点**：所有并行 `Send` 完成并合并 State 后，运行时才在下一个 superstep 调用 Barrier。

在本方案中，所有阶段任务都 `Send` 到同一个 `subagent_runner` 节点，形成 LangGraph 标准 map-reduce 结构：

```text
StageDispatcher
   ├─ Send(subagent_runner, Task A)
   ├─ Send(subagent_runner, Task B)
   └─ Send(subagent_runner, Task C)
                    ↓
               StageBarrier
```

StageBarrier 本身不负责“阻塞等待”，而负责：

- 校验本阶段预期 Task 是否都有结果。
- 校验结果是否成功。
- 将 `current_stage_index` 移到下一阶段。
- 决定继续调度下一 Stage，还是进入最终汇总。

### 8.3 阶段执行对应的 Superstep

```text
Superstep 0：Planner 生成依赖计划并完成拓扑分层
Superstep 1：StageDispatcher 分发 Stage 0
Superstep 2：Stage 0 的多个 Subagent 并行执行
Superstep 3：StageBarrier 校验 Stage 0 并推进索引
Superstep 4：StageDispatcher 分发 Stage 1
Superstep 5：Stage 1 的 Subagent 执行
Superstep 6：StageBarrier 校验 Stage 1 并推进索引
...
最后：PrepareSynthesis → Synthesizer
```

## 九、完整参考代码

以下代码是与当前项目风格一致的架构改造参考，**没有直接写入运行目录，也未编译执行**。建议拆成四个文件逐步接入。

### 9.1 计划模型与拓扑分层

建议新增：`python-agent/app/graph/staged_plan.py`

```python
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field


# Subagent 白名单是唯一权威来源。Planner 通过结构化输出受 Literal 约束，
# 无法凭空生成未注册的 Subagent 名称。
SubagentName = Literal["search", "analysis", "writing", "chat"]

MAX_TASKS = 12
MAX_STAGES = 6
MAX_TASKS_PER_STAGE = 4


class PlannedTask(BaseModel):
    """Planner 只描述任务和依赖，不直接决定并行线程。"""

    task_id: str = Field(min_length=1, max_length=64)
    subagent: SubagentName
    instruction: str = Field(min_length=1, max_length=2000)
    depends_on: list[str] = Field(default_factory=list)


class DependencyPlan(BaseModel):
    tasks: list[PlannedTask] = Field(min_length=1, max_length=MAX_TASKS)
    required_skills: list[str] = Field(default_factory=list)


class ExecutionStage(BaseModel):
    stage_id: str
    tasks: list[PlannedTask]


def build_execution_stages(plan: DependencyPlan) -> list[ExecutionStage]:
    """
    使用 Kahn 拓扑排序按层划分 Stage。

    同一轮所有入度为 0 的任务互不依赖，放入同一 Stage 并行执行；
    删除这一层后，新出现的入度为 0 的任务进入下一 Stage。
    """
    tasks = plan.tasks
    task_by_id = {task.task_id: task for task in tasks}

    if len(task_by_id) != len(tasks):
        raise ValueError("Planner 生成了重复的 task_id")

    original_order = {task.task_id: index for index, task in enumerate(tasks)}
    indegree = {task.task_id: 0 for task in tasks}
    successors: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        unique_dependencies = set(task.depends_on)
        if len(unique_dependencies) != len(task.depends_on):
            raise ValueError(f"任务 {task.task_id} 存在重复依赖")

        for dependency_id in task.depends_on:
            if dependency_id not in task_by_id:
                raise ValueError(
                    f"任务 {task.task_id} 依赖不存在的任务 {dependency_id}"
                )
            if dependency_id == task.task_id:
                raise ValueError(f"任务 {task.task_id} 不能依赖自身")

            indegree[task.task_id] += 1
            successors[dependency_id].append(task.task_id)

    ready = sorted(
        (task_id for task_id, degree in indegree.items() if degree == 0),
        key=original_order.get,
    )
    stages: list[ExecutionStage] = []
    processed_count = 0

    while ready:
        current_task_ids = ready
        ready = []

        if len(current_task_ids) > MAX_TASKS_PER_STAGE:
            raise ValueError(
                f"单阶段任务数 {len(current_task_ids)} 超过上限 "
                f"{MAX_TASKS_PER_STAGE}"
            )

        stage = ExecutionStage(
            stage_id=f"stage_{len(stages)}",
            tasks=[task_by_id[task_id] for task_id in current_task_ids],
        )
        stages.append(stage)
        processed_count += len(current_task_ids)

        for completed_task_id in current_task_ids:
            for successor_id in successors[completed_task_id]:
                indegree[successor_id] -= 1
                if indegree[successor_id] == 0:
                    ready.append(successor_id)

        ready.sort(key=original_order.get)

    if processed_count != len(tasks):
        cyclic_task_ids = [
            task_id for task_id, degree in indegree.items() if degree > 0
        ]
        raise ValueError(f"任务依赖存在环: {cyclic_task_ids}")

    if len(stages) > MAX_STAGES:
        raise ValueError(f"阶段数 {len(stages)} 超过上限 {MAX_STAGES}")

    _validate_side_effect_stages(stages)
    return stages


def _validate_side_effect_stages(stages: list[ExecutionStage]) -> None:
    """
    Writing 可能包含 interrupt、保存草稿等副作用。
    第一版限制一个阶段最多一个 writing，降低并行审批和重复写入复杂度。
    """
    for stage in stages:
        writing_count = sum(
            1 for task in stage.tasks if task.subagent == "writing"
        )
        if writing_count > 1:
            raise ValueError(
                f"阶段 {stage.stage_id} 包含多个 writing 任务，不允许并行副作用"
            )
```

### 9.2 分层算法示例

输入：

```python
plan = DependencyPlan(tasks=[
    PlannedTask(
        task_id="platform_search",
        subagent="search",
        instruction="搜索站内文章",
    ),
    PlannedTask(
        task_id="web_search",
        subagent="search",
        instruction="搜索外部最新资料",
    ),
    PlannedTask(
        task_id="compare",
        subagent="analysis",
        instruction="对比两类资料",
        depends_on=["platform_search", "web_search"],
    ),
    PlannedTask(
        task_id="draft",
        subagent="writing",
        instruction="根据分析结果生成文章",
        depends_on=["compare"],
    ),
])

stages = build_execution_stages(plan)
```

分层过程：

```text
初始入度：
platform_search = 0
web_search      = 0
compare         = 2
draft           = 1

第一轮入度为 0：platform_search、web_search
→ Stage 0，并行执行

移除 Stage 0 后：compare 入度变成 0
→ Stage 1

移除 compare 后：draft 入度变成 0
→ Stage 2
```
### 9.3 阶段化 State

建议新增：`python-agent/app/graph/staged_state.py`

与当前 `list + add` 相比，任务结果使用 `task_id -> result` 字典更适合解析依赖，也能防止同一 Task 静默产生重复结果。

```python
from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field


RESET_RESULTS_KEY = "__reset_task_results__"


class Principal(BaseModel):
    """
    调用方身份与权限上下文。

    只能由服务端在请求入口构造，来源是会话或 JWT，绝不允许由 LLM 输出、
    工具参数或 Planner 生成。Subagent 只读，不能修改也不能提权。
    """

    model_config = {"frozen": True}

    user_id: int
    role: Literal["anonymous", "user", "author", "admin"] = "user"
    # 本次请求可见的文档范围，编译进检索层 filter
    visible_scopes: list[Literal["public", "own", "followed"]] = Field(
        default_factory=lambda: ["public"]
    )

    def can_read_all_statuses(self) -> bool:
        return self.role == "admin"


class ExecutionBudget(BaseModel):
    """单次 run 的资源上限，用于阻断重试放大和无限规划。"""

    max_replans: int = 1
    max_tool_calls_per_task: int = 4
    max_total_tasks: int = 12
    deadline_ts: float | None = None


def merge_task_results(
    current: dict[str, dict] | None,
    update: dict[str, dict] | None,
) -> dict[str, dict]:
    """并行 Task 的结果 reducer；Planner 可用特殊标记开启新一轮计划。"""
    current = current or {}
    update = update or {}

    if RESET_RESULTS_KEY in update:
        if len(update) != 1:
            raise ValueError("重置标记不能和普通任务结果同时提交")
        return {}

    merged = dict(current)
    for task_id, result in update.items():
        if task_id in merged:
            raise ValueError(f"任务 {task_id} 产生了重复结果")
        merged[task_id] = result
    return merged


def merge_retrieval_history(
    current: dict | None,
    update: dict | None,
) -> dict:
    """
    跨轮累积的检索足迹，故意不响应 RESET_RESULTS_KEY。

    replan 会清空 task_results，但必须保留"已经检索过什么"，
    否则第二轮无法排除上一轮召回过的文档，也无法避免重复查询。
    """
    current = current or {"seen_doc_keys": [], "tried_queries": [], "tried_modes": []}
    if not update:
        return current

    merged = {
        "seen_doc_keys": list(current["seen_doc_keys"]),
        "tried_queries": list(current["tried_queries"]),
        "tried_modes": list(current["tried_modes"]),
    }
    for key in merged:
        for item in update.get(key, []):
            if item not in merged[key]:
                merged[key].append(item)
    return merged


class StagedAgentState(TypedDict):
    # 请求与会话上下文
    # principal 替代裸 user_id：单靠 user_id 无法表达"这个用户能看哪些文档"
    principal: dict
    user_message: str
    history_messages: list[dict]
    required_skills: list[str]
    cancelled: bool
    budget: dict

    # Planner 生成并经代码拓扑分层后的执行计划
    execution_stages: list[dict]
    current_stage_index: int

    # 上一轮计划，replan 时注入 Planner，避免生成完全相同的计划
    previous_plan: NotRequired[list[dict]]

    # 多个 subagent_runner 并行写入，使用 reducer 合并
    task_results: Annotated[dict[str, dict], merge_task_results]

    # 跨 replan 累积，不被 reset 清空
    retrieval_history: Annotated[dict, merge_retrieval_history]

    # 仅存在于 Send 创建的分支 State，不由并行节点写回全局
    current_task: NotRequired[dict]
    dependency_results: NotRequired[list[dict]]
    allowed_tools: NotRequired[list[str]]

    # PrepareResults 单节点生成，供现有 Reflector/Synthesizer 使用
    worker_results: list[dict]
    article_cards: list[dict]
    citations: list[dict]
    draft_article_id: int | None

    # 反思与重规划
    needs_retry: bool
    retry_count: int
    reflection_feedback: str
    # 区分"检索没召回到东西"和"召回了但写得不好"，决定重规划还是只重写
    retry_reason: NotRequired[Literal["retrieval", "generation"]]
    final_reply: str
```

三个字段的设计理由：

- `principal` 而不是 `user_id`：权限判断需要角色和可见范围，裸 `user_id` 只能表示"是谁"，不能表示"能看什么"。用 `frozen=True` 的 Pydantic 模型防止 Subagent 篡改。
- `retrieval_history` 使用独立 reducer 且不响应 reset：这是 replan 能真正改变检索结果的前提，详见第十七节。
- `retry_reason`：生成质量差不应该触发重新检索，检索没命中也不应该只改写作 Prompt，两者的修复路径不同。

为什么不继续让每个 Subagent 直接写 `worker_results`：

- 同一个 Worker 可能在一个 Stage 中执行多个 Task，仅靠 `worker_name` 无法区分。
- 后序任务要按 `depends_on` 精确读取结果，字典查询更直接。
- 所有 Stage 完成后，再由单节点按计划顺序生成现有 `worker_results`，可继续复用 Reflector 和 Synthesizer。

### 9.4 阶段化 Planner

建议新增：`python-agent/app/graph/nodes/staged_planner.py`

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import get_llm
from app.graph.staged_plan import DependencyPlan, build_execution_stages
from app.graph.staged_state import RESET_RESULTS_KEY, StagedAgentState
from app.skills.registry import skill_registry


STAGED_PLANNER_PROMPT = """你是 Main Agent 的任务规划器。

【可用 Subagent】
- search：检索站内文章和外部信息
- analysis：基于已有资料进行分析、对比和总结
- writing：基于已有资料和分析结果生成文章
- chat：普通问答和闲聊

【规划要求】
1. 输出 Task 列表，并用 depends_on 表达数据依赖。
2. 只有互不依赖的 Task 才能并行。
3. analysis 如果需要搜索结果，必须依赖对应 search Task。
4. writing 如果需要资料或分析结果，必须声明对应依赖。
5. task_id 必须唯一、稳定、语义清晰。
6. 简单问题只生成一个 Task。
7. 不要自行生成 Stage，后端会执行拓扑分层和环检测。

【Skill 目录】
{skill_catalog}
"""

REPLAN_SUFFIX = """
【重规划上下文】
上一轮计划已执行但结果不合格，你必须生成一个与上一轮实质不同的计划。

上一轮任务：
{previous_tasks}

质量评审反馈：
{feedback}

已经检索过的查询（不要原样重复）：
{tried_queries}

已经使用过的检索模式：
{tried_modes}

【重规划策略，至少采用一种】
1. 增加检索路数：只搜过站内就补一路联网，反之亦然。
2. 拆解检索意图：把一个笼统的检索任务拆成多个角度明确的子任务。
3. 调整检索措辞：换术语、补全省略的主语、使用领域同义词。
4. 补充中间环节：资料零散时先插入一个 analysis 任务再交给 writing。

禁止输出与上一轮 instruction 相同的任务。
"""


def _format_previous_tasks(previous_plan: list[dict]) -> str:
    if not previous_plan:
        return "无"
    lines = []
    for stage in previous_plan:
        for task in stage.get("tasks", []):
            lines.append(
                f"- {task['task_id']} ({task['subagent']}): {task['instruction']}"
            )
    return "\n".join(lines)


async def staged_planner_node(state: StagedAgentState) -> dict:
    """
    首次规划与重规划共用同一个节点，通过 retry_count 区分。

    关键点：重规划必须改变模型输入，否则 temperature=0 的结构化输出
    会生成逐字相同的计划，重试等于白跑一遍。
    """
    retry_count = state.get("retry_count", 0)
    is_replan = retry_count > 0

    system_prompt = STAGED_PLANNER_PROMPT.format(
        skill_catalog=skill_registry.get_catalog(),
    )

    if is_replan:
        history = state.get("retrieval_history") or {}
        system_prompt += REPLAN_SUFFIX.format(
            previous_tasks=_format_previous_tasks(state.get("previous_plan", [])),
            feedback=state.get("reflection_feedback", "无具体反馈"),
            tried_queries=", ".join(history.get("tried_queries", [])) or "无",
            tried_modes=", ".join(history.get("tried_modes", [])) or "无",
        )

    messages = [SystemMessage(content=system_prompt)]

    for message in state.get("history_messages", []):
        role = message.get("role")
        content = message.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))

    messages.append(HumanMessage(content=state["user_message"]))

    # 首次规划要稳定可复现，重规划需要跳出上一轮的局部最优。
    planner = get_llm(temperature=0.4 if is_replan else 0).with_structured_output(
        DependencyPlan,
        method="function_calling",
    )
    plan: DependencyPlan = await planner.ainvoke(messages)

    # 确定性代码负责校验、环检测和阶段划分；失败直接暴露，不静默降级。
    stages = build_execution_stages(plan)
    stage_dicts = [stage.model_dump() for stage in stages]

    return {
        "execution_stages": stage_dicts,
        "previous_plan": stage_dicts,
        "current_stage_index": 0,
        "required_skills": plan.required_skills,
        # 只清空任务结果；retrieval_history 由独立 reducer 保留
        "task_results": {RESET_RESULTS_KEY: {}},
        "worker_results": [],
        "article_cards": [],
        "citations": [],
        "draft_article_id": None,
        # 注意：这里绝对不能写 "retry_count": 0。
        # Reflector 依赖 retry_count 递增来终止循环，重置会导致无限 replan。
    }
```

`temperature` 采用两档而不是固定 0：首次规划希望同一问题得到稳定可复现的计划，便于排查和回归测试；重规划的目标恰恰是跳出上一轮的输出，此时确定性是缺点。同时靠 `REPLAN_SUFFIX` 提供明确的差异化指令，而不是仅仅依赖温度扰动。

这里选择“Planner 输出依赖，代码划分 Stage”，而不是让模型直接输出 Stage，原因是：

- 拓扑排序是确定性问题，不需要交给概率模型。
- 代码可以可靠检测循环依赖、未知 Task 和非法并行。
- 同一依赖计划可以用不同并发限制重新分层。
- 面试时可以体现“模型做语义理解，代码保证执行正确性”的边界设计。
### 9.5 StageDispatcher：只分发当前阶段

建议新增：`python-agent/app/graph/nodes/stage_executor.py`

```python
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from langgraph.errors import GraphInterrupt
from langgraph.types import Send

from app.graph.nodes.analysis_worker import analysis_worker_node
from app.graph.nodes.chat_worker import chat_worker_node
from app.graph.nodes.search_worker import search_worker_node
from app.graph.nodes.writing_worker import writing_worker_node
from app.graph.staged_state import StagedAgentState


log = logging.getLogger(__name__)

SubagentHandler = Callable[[dict], Awaitable[dict]]


class SubagentSpec(NamedTuple):
    """
    Subagent 定义。

    隔离维度不只有 System Prompt，还包括工具白名单：
    只换 Prompt 不换工具，等于让每个 Subagent 都持有全量能力，
    职责边界形同虚设，也无法做最小权限。
    """

    handler: SubagentHandler
    allowed_tools: list[str]


# 工具白名单是能力边界，不是建议。search 不含 search_articles*：
# 站内 RAG 已由 Subagent 内部的确定性前置链路完成，
# 再暴露裸召回工具会造成双检索入口，详见第十五节。
SUBAGENT_SPECS: dict[str, SubagentSpec] = {
    "search": SubagentSpec(
        handler=search_worker_node,
        allowed_tools=["web_search", "get_trending_topics"],
    ),
    "analysis": SubagentSpec(
        handler=analysis_worker_node,
        allowed_tools=["get_article_comments"],
    ),
    "writing": SubagentSpec(
        handler=writing_worker_node,
        allowed_tools=[],
    ),
    "chat": SubagentSpec(
        handler=chat_worker_node,
        allowed_tools=["get_user_articles"],
    ),
}


class StageExecutionError(RuntimeError):
    pass


def stage_dispatcher_node(state: StagedAgentState) -> dict:
    """仅作为图中的显式调度节点；实际 Send 由条件路由函数生成。"""
    if state.get("cancelled"):
        raise StageExecutionError("用户已取消，停止分发新阶段")

    stage_index = state["current_stage_index"]
    if stage_index >= len(state["execution_stages"]):
        raise StageExecutionError("当前阶段索引越界")
    return {}


def dispatch_current_stage(state: StagedAgentState) -> list[Send]:
    """将当前 Stage 的所有 Task 发送到同一个 map 节点并行执行。"""
    stage_index = state["current_stage_index"]
    stage = state["execution_stages"][stage_index]
    task_results = state.get("task_results", {})

    sends: list[Send] = []
    for task in stage["tasks"]:
        dependency_results: list[dict] = []

        for dependency_id in task.get("depends_on", []):
            dependency_result = task_results.get(dependency_id)
            if dependency_result is None:
                raise StageExecutionError(
                    f"任务 {task['task_id']} 缺少依赖结果 {dependency_id}"
                )
            if dependency_result.get("status") != "success":
                raise StageExecutionError(
                    f"任务 {task['task_id']} 的依赖 {dependency_id} 未成功"
                )
            dependency_results.append(dependency_result)

        spec = SUBAGENT_SPECS.get(task["subagent"])
        if spec is None:
            raise StageExecutionError(f"未注册 Subagent: {task['subagent']}")

        branch_state = {
            # 身份与权限：必须完全一致且不可篡改，来源是服务端会话
            "principal": state["principal"],

            # 任务无关的稳定上下文
            "user_message": state["user_message"],
            "required_skills": state.get("required_skills", []),
            "cancelled": state.get("cancelled", False),
            "budget": state.get("budget", {}),

            # 历史消息按 Subagent 需求裁剪，不全量广播：
            # search 需要历史做指代消解，analysis/writing 已有 dependency_results
            "history_messages": _scope_history(
                state.get("history_messages", []),
                task["subagent"],
            ),

            # 只把与本次重试原因相关的反馈下发，避免分析意见污染检索任务
            "reflection_feedback": _scope_feedback(
                state.get("reflection_feedback", ""),
                state.get("retry_reason"),
                task["subagent"],
            ),

            # 当前分支独有数据，不写回全局标量字段
            "current_task": {
                **task,
                "stage_id": stage["stage_id"],
                "stage_index": stage_index,
            },
            "dependency_results": dependency_results,
            "allowed_tools": spec.allowed_tools,

            # 只读传入，供检索层排除已召回文档
            "retrieval_history": state.get("retrieval_history") or {},
        }
        sends.append(Send("subagent_runner", branch_state))

    if not sends:
        raise StageExecutionError(f"阶段 {stage['stage_id']} 没有可执行任务")
    return sends


# 历史消息的可见范围：多轮指代消解只有检索和闲聊需要，
# 分析和写作的输入应该来自 dependency_results 而不是原始对话。
_HISTORY_SCOPE: dict[str, int] = {
    "search": 6,
    "chat": 10,
    "analysis": 0,
    "writing": 0,
}


def _scope_history(history: list[dict], subagent: str) -> list[dict]:
    limit = _HISTORY_SCOPE.get(subagent, 0)
    return history[-limit:] if limit else []


def _scope_feedback(
    feedback: str,
    retry_reason: str | None,
    subagent: str,
) -> str:
    """
    反馈信号必须对齐修复路径。

    检索没命中就不要把"文章结构不清晰"传给 search，
    生成质量差也不要让 search 重跑一遍相同的检索。
    """
    if not feedback:
        return ""
    if retry_reason == "retrieval" and subagent != "search":
        return ""
    if retry_reason == "generation" and subagent == "search":
        return ""
    return feedback


def _build_task_input(task: dict, dependency_results: list[dict]) -> str:
    parts = [f"【当前任务】\n{task['instruction']}"]

    if dependency_results:
        parts.append("【前序任务结果】")
        for result in dependency_results:
            parts.append(
                f"--- task_id={result['task_id']}, "
                f"subagent={result['subagent']} ---\n"
                f"{result.get('content', '')}"
            )
            citations = result.get("citations", [])
            if citations:
                parts.append(
                    "引用信息：\n"
                    + json.dumps(citations, ensure_ascii=False)
                )

    return "\n\n".join(parts)


async def subagent_runner_node(state: dict) -> dict:
    """
    通用 map 节点。

    每个 Send 都会创建一次独立调用；所有调用可并行，但只返回以 task_id
    为 key 的 task_results 更新。当前任务和依赖结果不会覆盖全局 State。
    """
    task = state["current_task"]
    task_id = task["task_id"]
    subagent_name = task["subagent"]

    spec = SUBAGENT_SPECS.get(subagent_name)
    if spec is None:
        raise StageExecutionError(f"未注册 Subagent: {subagent_name}")
    handler = spec.handler

    if state.get("cancelled"):
        return {
            "task_results": {
                task_id: {
                    "task_id": task_id,
                    "stage_id": task["stage_id"],
                    "stage_index": task["stage_index"],
                    "subagent": subagent_name,
                    "status": "cancelled",
                    "content": "",
                    "error": "用户已取消",
                }
            }
        }

    # 适配现有 Worker：把阶段任务及前序结果放进它原来读取的 task_descriptions。
    local_state = dict(state)
    local_state["task_descriptions"] = {
        subagent_name: _build_task_input(
            task,
            state.get("dependency_results", []),
        )
    }
    local_state["worker_results"] = []
    local_state["article_cards"] = []
    local_state["citations"] = []
    local_state["retry_count"] = 0
    local_state["needs_retry"] = False
    local_state["final_reply"] = ""
    local_state["draft_article_id"] = None

    try:
        raw_update = await handler(local_state)
        worker_outputs = raw_update.get("worker_results", [])
        if len(worker_outputs) != 1:
            raise StageExecutionError(
                f"任务 {task_id} 应返回一个 Worker 结果，实际为 "
                f"{len(worker_outputs)} 个"
            )

        worker_output = worker_outputs[0]
        task_result = {
            "task_id": task_id,
            "stage_id": task["stage_id"],
            "stage_index": task["stage_index"],
            "subagent": subagent_name,
            "status": "success",
            "content": worker_output.get("result", ""),
            "article_cards": raw_update.get("article_cards", []),
            "citations": raw_update.get("citations", []),
            "draft_article_id": raw_update.get("draft_article_id"),
            "draft_title": worker_output.get("draft_title"),
            # 检索命中数量供 Reflector 区分"没召回"和"召回了但不好"
            "retrieved_count": len(raw_update.get("citations", [])),
            "error": None,
        }
        retrieval_trace = raw_update.get("retrieval_trace") or {}
    except GraphInterrupt:
        # interrupt/resume 是 LangGraph 控制流，不能当作普通 Worker 异常吞掉。
        raise
    except Exception as error:
        # 不伪装成功。记录失败结果，等待 Barrier 汇总后统一中止该阶段。
        log.exception(
            "Subagent 执行失败: task_id=%s, subagent=%s",
            task_id,
            subagent_name,
        )
        task_result = {
            "task_id": task_id,
            "stage_id": task["stage_id"],
            "stage_index": task["stage_index"],
            "subagent": subagent_name,
            "status": "failed",
            "content": "",
            "article_cards": [],
            "citations": [],
            "draft_article_id": None,
            "draft_title": None,
            "retrieved_count": 0,
            "error": f"{type(error).__name__}: {str(error)[:500]}",
        }
        retrieval_trace = {}

    update: dict = {"task_results": {task_id: task_result}}

    # 检索足迹跨 replan 累积，供下一轮排除已召回文档、避免重复查询
    if retrieval_trace:
        update["retrieval_history"] = {
            "seen_doc_keys": retrieval_trace.get("doc_keys", []),
            "tried_queries": retrieval_trace.get("queries", []),
            "tried_modes": retrieval_trace.get("modes", []),
        }
    return update
```

这里所有 Task 都发送到同一个 `subagent_runner`，而不是分别发送到四种图节点，目的是形成明确的 map-reduce fan-in：

```text
StageDispatcher → N 个 subagent_runner 实例 → 一个 StageBarrier
```

`subagent_runner` 内部再通过 `SUBAGENT_SPECS` 查表调用真实 Search/Analysis/Writing/Chat Subagent。未来这些 Subagent 可以从普通函数替换为独立 LangGraph 子图，StageDispatcher 无需变化。

注册表返回的是 `SubagentSpec` 而不是裸函数，因为 Subagent 的定义包含两部分：执行入口和能力边界。工具白名单在 `dispatch_current_stage()` 阶段就写入 `branch_state.allowed_tools`，Subagent 内部必须据此取工具，而不是调用 `get_all_tools()`。

### 9.6 StageBarrier：校验并推进阶段

继续写入 `stage_executor.py`：

```python
def stage_barrier_node(state: StagedAgentState) -> dict:
    """
    fan-in 节点。

    运行到这里时，本阶段所有 subagent_runner 的 task_results 已经过
    reducer 合并。Barrier 只做完整性/成功性校验和阶段索引推进。
    """
    stage_index = state["current_stage_index"]
    stage = state["execution_stages"][stage_index]
    task_results = state.get("task_results", {})

    expected_task_ids = {task["task_id"] for task in stage["tasks"]}
    completed_task_ids = {
        task_id
        for task_id, result in task_results.items()
        if result.get("stage_index") == stage_index
    }

    missing_task_ids = expected_task_ids - completed_task_ids
    if missing_task_ids:
        raise StageExecutionError(
            f"阶段 {stage['stage_id']} 结果不完整，缺少: "
            f"{sorted(missing_task_ids)}"
        )

    failed_results = [
        task_results[task_id]
        for task_id in expected_task_ids
        if task_results[task_id].get("status") != "success"
    ]
    if failed_results:
        failures = [
            {
                "task_id": result["task_id"],
                "status": result["status"],
                "error": result.get("error"),
            }
            for result in failed_results
        ]
        raise StageExecutionError(
            f"阶段 {stage['stage_id']} 执行失败: {failures}"
        )

    return {"current_stage_index": stage_index + 1}


def route_after_barrier(state: StagedAgentState) -> str:
    if state["current_stage_index"] < len(state["execution_stages"]):
        return "next_stage"
    return "all_stages_completed"
```

注意：Barrier 不使用 `while`、`sleep` 或锁等待 Worker。它被图运行时安排在 map superstep 之后执行；代码中的 `missing_task_ids` 是不变量校验，用于发现构图或 reducer 错误。
### 9.7 将 Task 结果转换为现有 Synthesizer 输入

建议继续写入 `stage_executor.py`：

```python
def prepare_results_node(state: StagedAgentState) -> dict:
    """所有 Stage 完成后，按计划顺序构建现有 worker_results。"""
    task_results = state["task_results"]
    ordered_results: list[dict] = []
    article_cards: list[dict] = []
    citations: list[dict] = []
    draft_article_id: int | None = None

    seen_article_ids: set[str] = set()
    seen_citations: set[str] = set()

    for stage in state["execution_stages"]:
        for task in stage["tasks"]:
            task_id = task["task_id"]
            result = task_results.get(task_id)
            if result is None or result.get("status") != "success":
                raise StageExecutionError(
                    f"无法汇总未成功的任务: {task_id}"
                )

            worker_result = {
                "task_id": task_id,
                "stage_id": stage["stage_id"],
                "worker_name": result["subagent"],
                "result": result.get("content", ""),
            }
            if result.get("draft_article_id") is not None:
                worker_result["draft_article_id"] = result["draft_article_id"]
                worker_result["draft_title"] = result.get("draft_title")
                draft_article_id = result["draft_article_id"]
            ordered_results.append(worker_result)

            for card in result.get("article_cards", []):
                article_id = str(card.get("articleId", ""))
                if article_id and article_id not in seen_article_ids:
                    seen_article_ids.add(article_id)
                    article_cards.append(card)

            for citation in result.get("citations", []):
                citation_key = json.dumps(
                    citation,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if citation_key not in seen_citations:
                    seen_citations.add(citation_key)
                    citations.append(citation)

    return {
        "worker_results": ordered_results,
        "article_cards": article_cards,
        "citations": citations,
        "draft_article_id": draft_article_id,
    }
```

这个节点只有一个实例执行，因此 `worker_results`、`article_cards` 和 `citations` 不再需要并行 reducer。现有 Reflector 和 Synthesizer 可以继续读取它们。

### 9.8 完整 LangGraph 构图

建议新增：`python-agent/app/graph/staged_builder.py`

```python
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.reflector import reflector_node
from app.graph.nodes.synthesizer import synthesizer_node
from app.graph.nodes.stage_executor import (
    dispatch_current_stage,
    prepare_results_node,
    route_after_barrier,
    stage_barrier_node,
    stage_dispatcher_node,
    subagent_runner_node,
)
from app.graph.nodes.staged_planner import staged_planner_node
from app.graph.staged_state import StagedAgentState


def _route_after_reflector(state: StagedAgentState) -> str:
    """
    三路而不是两路：证据不足才重规划，表达不好只重跑合成。
    详见第十六节。
    """
    if not state.get("needs_retry"):
        return "synthesize"

    budget = state.get("budget", {})
    if state.get("retry_count", 0) >= budget.get("max_replans", 1):
        return "synthesize"          # 预算用尽，带现有结果收尾

    if state.get("retry_reason") == "retrieval":
        return "replan"              # 证据不足，重新规划检索
    return "synthesize"              # 证据够但表达差，交给 synthesizer 重写


def build_staged_graph() -> StateGraph:
    graph = StateGraph(StagedAgentState)

    graph.add_node("planner", staged_planner_node)
    graph.add_node("stage_dispatcher", stage_dispatcher_node)
    graph.add_node("subagent_runner", subagent_runner_node)
    graph.add_node("stage_barrier", stage_barrier_node)
    graph.add_node("prepare_results", prepare_results_node)
    graph.add_node("reflector", reflector_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "stage_dispatcher")

    # 当前 Stage 的 N 个 Task → N 个 subagent_runner 并行实例。
    graph.add_conditional_edges(
        "stage_dispatcher",
        dispatch_current_stage,
    )

    # Map-Reduce fan-in：本 Stage 所有 runner 完成后进入 Barrier。
    graph.add_edge("subagent_runner", "stage_barrier")

    # Barrier 已把 current_stage_index + 1。
    graph.add_conditional_edges(
        "stage_barrier",
        route_after_barrier,
        {
            "next_stage": "stage_dispatcher",
            "all_stages_completed": "prepare_results",
        },
    )

    graph.add_edge("prepare_results", "reflector")
    graph.add_conditional_edges(
        "reflector",
        _route_after_reflector,
        {
            "replan": "planner",
            "synthesize": "synthesizer",
        },
    )
    graph.add_edge("synthesizer", END)
    return graph
```

然后复用当前 Redis Checkpointer：

```python
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from app.config import settings


_compiled_staged_graph = None


async def get_staged_graph():
    global _compiled_staged_graph
    if _compiled_staged_graph is not None:
        return _compiled_staged_graph

    password = (
        f":{settings.REDIS_STACK_PASSWORD}@"
        if settings.REDIS_STACK_PASSWORD
        else ""
    )
    redis_url = (
        f"redis://{password}{settings.REDIS_STACK_HOST}:"
        f"{settings.REDIS_STACK_PORT}/{settings.REDIS_STACK_DB}"
    )
    checkpointer = AsyncRedisSaver(redis_url=redis_url)
    await checkpointer.asetup()

    _compiled_staged_graph = build_staged_graph().compile(
        checkpointer=checkpointer,
    )
    return _compiled_staged_graph
```

### 9.9 FastAPI 初始 State 改造

当前 `main.py` 组装的扁平字段：

```python
"active_workers": [],
"task_descriptions": {},
"worker_results": [],
```

改为：

```python
# principal 必须在这里从会话/JWT 构造，这是整条链路唯一的可信身份来源。
# 请求体里的 user_id 只能用于校验，不能直接采信。
principal = await build_principal_from_session(request)

initial_state: StagedAgentState = {
    "principal": principal.model_dump(),
    "user_message": processed_message,
    "history_messages": context,
    "required_skills": [],
    "cancelled": False,
    "budget": ExecutionBudget().model_dump(),

    "execution_stages": [],
    "current_stage_index": 0,
    "task_results": {},
    "retrieval_history": {
        "seen_doc_keys": [],
        "tried_queries": [],
        "tried_modes": [],
    },

    "worker_results": [],
    "article_cards": [],
    "citations": [],
    "draft_article_id": None,

    "needs_retry": False,
    "retry_count": 0,
    "reflection_feedback": "",
    "final_reply": "",
}
```

`build_principal_from_session()` 需要服务端查库确定角色与可见范围：

```python
async def build_principal_from_session(request) -> Principal:
    """身份只认服务端会话，不认请求体和模型输出。"""
    session_user_id = await resolve_user_id_from_token(request)
    if session_user_id is None:
        return Principal(user_id=0, role="anonymous", visible_scopes=["public"])

    role = await load_user_role(session_user_id)
    return Principal(
        user_id=session_user_id,
        role=role,
        visible_scopes=["public", "own"],
    )
```

执行配置仍然可以使用当前会话作为 thread：

```python
config = {
    "configurable": {
        "thread_id": f"conv_{conv_id}",
    }
}
result = await graph.ainvoke(initial_state, config=config)
```

生产环境还应限制同一 conversation 同时只能有一个运行中的 run，避免两个阶段计划竞争同一 Checkpoint。

## 十、完整执行时序示例

假设 Planner 生成四个任务：

```text
A：站内搜索，无依赖
B：联网搜索，无依赖
C：对比分析，依赖 A、B
D：文章写作，依赖 C
```

后端拓扑分层：

```text
Stage 0 = [A, B]
Stage 1 = [C]
Stage 2 = [D]
```

实际执行：

```text
1. Planner
   - 输出 Task A/B/C/D 和 depends_on
   - build_execution_stages() 生成 Stage 0/1/2
   - current_stage_index = 0

2. StageDispatcher(Stage 0)
   - Send(A → subagent_runner)
   - Send(B → subagent_runner)

3. Superstep：A、B 并行
   - A 返回 task_results["A"]
   - B 返回 task_results["B"]
   - reducer 合并 A、B

4. StageBarrier(Stage 0)
   - 检查 A、B 是否都有 success 结果
   - current_stage_index = 1

5. StageDispatcher(Stage 1)
   - 读取 task_results["A"] 和 task_results["B"]
   - 构造 C 的 dependency_results
   - Send(C → subagent_runner)

6. Superstep：C 执行
   - AnalysisSubagent 获得 A、B 的真实结果
   - 返回 task_results["C"]

7. StageBarrier(Stage 1)
   - 检查 C 成功
   - current_stage_index = 2

8. StageDispatcher(Stage 2)
   - 把 C 的分析结论注入 D
   - Send(D → subagent_runner)

9. WritingSubagent 执行
   - 基于真实分析结果生成内容

10. StageBarrier → PrepareResults → Reflector → Synthesizer
```

## 十一、HITL 与阶段化执行的特殊处理

当前 `writing_worker_node()` 在同一个节点中先生成草稿，再调用 `interrupt()`。LangGraph 恢复中断节点时会从节点开头重新执行，因此中断前的模型调用必须保证可重放，或者避免放在同一个节点。

更稳健的拆分方式是：

```text
Stage N：WritingSubagent 只生成结构化草稿
   ↓
ApprovalNode：interrupt，等待 approve/reject/修改意见
   ↓ approve
SaveDraftNode：幂等保存草稿
   ↓
后续 Stage / Synthesizer
```

这样：

- 草稿生成结果已经进入 Checkpoint。
- resume 不需要重新调用写作模型。
- 审批与保存副作用分离。
- `SaveDraftNode` 可使用 runId/taskId 保证幂等。

如果继续在通用 `subagent_runner` 内调用现有 WritingWorker，异常捕获必须让 LangGraph 的中断异常继续向上传播，不能把 interrupt 当普通失败处理：

```python
from langgraph.errors import GraphInterrupt

try:
    raw_update = await handler(local_state)
except GraphInterrupt:
    raise
except Exception as error:
    # 记录真正的 Worker 失败
    ...
```

## 十二、错误处理策略

阶段执行的基线是 Fail-Fast：

- 当前 Stage 任一必需 Task 失败，Barrier 终止后续 Stage。
- 不允许 Analysis 在搜索失败后假装有资料继续分析。
- 不允许 Writing 在依赖缺失时凭模型常识继续写作。
- 错误携带 `stage_id`、`task_id`、`subagent` 和 traceId。

### 12.1 只有 Fail-Fast 会留下一个恢复空洞

如果 Barrier 对所有失败都直接 `raise`，会出现一个容易被忽略的断裂：

```text
检索抛异常（ES 超时、字段缺失、下游 5xx）
    → Barrier raise StageExecutionError
    → 整图失败，走不到 Reflector
    → 没有任何重试机会

检索成功但零召回（status=success，content="未找到相关资料"）
    → 正常走到 Reflector
    → 可以触发 replan
```

也就是说，**最需要重试的硬失败反而是唯一没有恢复路径的**，而质量问题却有。所以策略字段不能只有一个值。

### 12.2 三档失败策略

```python
FailurePolicy = Literal["fail_fast", "retry_stage", "degrade"]
```

| 策略 | 语义 | 适用 Task |
|---|---|---|
| `fail_fast` | 立即终止整个 run | 写作、保存草稿等有副作用的任务 |
| `retry_stage` | 同阶段原地重试，受 `max_stage_retries` 限制 | 检索类任务遇到超时、限流、5xx |
| `degrade` | 标记为失败但允许后续阶段继续，下游必须能处理缺失依赖 | 可选的补充检索 |

判断依据是**错误是否可能自愈**：

```python
_TRANSIENT_ERRORS = (TimeoutError, ConnectionError)


def classify_failure(task: dict, error: Exception) -> str:
    if task["subagent"] == "writing":
        return "fail_fast"          # 有副作用，不能盲目重试
    if isinstance(error, _TRANSIENT_ERRORS):
        return "retry_stage"        # 瞬时故障，原地重试有意义
    if task.get("optional"):
        return "degrade"
    return "fail_fast"
```

`degrade` 有一个硬约束：下游 Task 必须显式声明能容忍该依赖缺失，否则仍然 `fail_fast`。不允许出现"依赖悄悄没了，下游用常识补上"的情况，那本质上是把幻觉合法化。

只有明确标记为可选的 Task 才允许 `degrade`；不能通过隐式 fallback 掩盖依赖故障。

### 12.3 与 9.6 基线实现的关系

第 9.6 节的 `stage_barrier_node()` 是**基线版本**，对任何失败都直接 `raise StageExecutionError`，等价于全局 `fail_fast`。接入三档策略时，Barrier 需要改为按 `classify_failure()` 的结果分流：

```text
fail_fast    → raise，终止整个 run
retry_stage  → 保持 current_stage_index 不变，累加 stage_retry_count 后重新分发本阶段
degrade      → 记录失败结果，推进 stage_index，由下游校验是否能容忍
```

`retry_stage` 需要在 State 中增加 `stage_retry_count: dict[str, int]`，按 `stage_id` 计数并受 `ExecutionBudget` 约束，否则瞬时故障会导致该阶段无限重发。建议先上线基线 `fail_fast`，在有真实故障数据后再接入分流。

## 十三、SSE 进度协议调整

阶段化后建议增加结构化进度事件：

```text
event: stage_started
data: {"stageIndex":0,"stageId":"stage_0","taskIds":["A","B"]}

event: task_started
data: {"stageId":"stage_0","taskId":"A","subagent":"search"}

event: task_completed
data: {"stageId":"stage_0","taskId":"A","status":"success"}

event: stage_completed
data: {"stageIndex":0,"stageId":"stage_0"}
```

前端可以展示：

```text
正在收集资料（1/3）
  ✓ 站内文章搜索
  … 联网搜索
正在分析资料（2/3）
正在生成草稿（3/3）
```

不要把 Subagent 的内部 Prompt、完整 Tool 参数或推理过程发送给前端。

## 十四、RAG 调用归属与检索入口唯一性

### 14.1 三种主流模式

| 模式 | 谁决定检索 | 优点 | 代价 |
|---|---|---|---|
| 编排层前置检索 | 编排代码，固定执行 | 延迟稳定、召回可量化、便于回归测试 | 不需要检索时也检索 |
| RAG 作为工具 | 主 Agent 的 LLM | 灵活，能多轮追问式检索 | 决策不稳定，中间产物污染主上下文 |
| 专职检索 Subagent | 主 Agent 下发意图，Subagent 决定策略 | 上下文隔离，检索链路可独立演进 | 多一跳调度开销 |

### 14.2 本架构的选择：意图与策略分层

```text
Main Agent（staged_planner）
    决定：要不要检索、检索几路、每路检索什么
    产出：PlannedTask(subagent="search", instruction="搜索平台内 Spring Boot 相关文章")
         ↓
Search Subagent（search_worker_node）
    决定：怎么检索
    执行：query_rewrite → filter_resolver → hybrid_search(RRF) → rerank → citation
    回传：压缩后的 content + citations
```

Main Agent **不直接调用 RAG**，也不感知 chunk、embedding、RRF 这些细节。它只表达检索意图，用 `depends_on` 表达"谁要用检索结果"。

这样划分的核心收益是**上下文隔离**。粗检索会产出 `COARSE_TOP_K` 条候选、每条数百 token 的原文片段、被重排丢弃的结果和相似度分数。这些如果进入 Main Agent 的窗口，会挤占预算并干扰后续规划。`_build_task_input()` 只向下游传递 `content` 和 `citations`：

```python
parts.append(f"--- task_id={result['task_id']}, subagent={result['subagent']} ---\n"
             f"{result.get('content', '')}")
```

### 14.3 检索入口必须唯一

这是最容易踩的反模式：**同一次请求里既做了前置检索，又把检索工具暴露给同一个 LLM**。

```text
反模式：
    前置链路产出 rag_context（已改写、已 RRF、已重排、带引用）
        ↓ 拼进 prompt
    LLM 又 tool_call search_articles(query)（裸召回，无改写无重排无引用）
        ↓
    模型可能用质量更差的第二批结果覆盖第一批结论
```

后果不只是重复消耗：两条路径的**证据质量不同但模型无法区分**，而裸召回结果没有 citation 编号，会导致最终回答里出现无法回溯来源的论述。

因此 `SUBAGENT_SPECS` 中 `search` 的白名单**故意不含** `search_articles` 和 `search_articles_by_knn`：

```python
"search": SubagentSpec(
    handler=search_worker_node,
    allowed_tools=["web_search", "get_trending_topics"],
),
```

站内检索只能走 Subagent 内部的确定性链路，工具层只保留平台外能力。

### 14.4 Subagent 内部必须消费白名单

传下来的 `allowed_tools` 不是文档说明，必须真正生效。现有 `search_worker_node` 的写法需要修改：

```python
# 修改前：全量工具，白名单形同虚设
all_tools = tool_registry.get_all_tools()

# 修改后：按分支下发的白名单取工具
allowed = state.get("allowed_tools", [])
tools = tool_registry.get_tools(allowed)
```

`ToolRegistry.get_tools(names)` 已经支持按名过滤，不需要新增能力。

### 14.5 检索链路需要回传足迹

为支撑第十六节的重规划，`search_worker_node` 除了业务结果外还要回传 `retrieval_trace`：

```python
return {
    "worker_results": [{"worker_name": "search", "result": reply}],
    "article_cards": article_cards,
    "citations": [c.__dict__ for c in citations],
    "retrieval_trace": {
        "doc_keys": [d.get("doc_key") for d in ranked if d.get("doc_key")],
        "queries": rewrite_result["semantic_queries"] + rewrite_result["keywords"],
        "modes": [search_mode],
    },
}
```

`subagent_runner_node` 会把它汇入 `retrieval_history`，该字段跨 replan 累积且不被 reset 清空。

---

## 十五、权限模型与上下文分层

### 15.1 上下文不是"一致"或"隔离"的二选一，而是按层区分

| 层 | 策略 | 本架构实现 |
|---|---|---|
| 身份与权限 | **必须完全一致且不可篡改** | `principal` 由服务端构造，`frozen=True`，逐分支透传 |
| 任务目标 | 一致但精确裁剪 | `current_task.instruction` |
| 依赖数据 | 按 `depends_on` 精确注入 | `dependency_results`，缺失即 fail-fast |
| 对话历史 | 按 Subagent 需求裁剪 | `_scope_history()`，analysis/writing 不给历史 |
| 反馈信号 | 按重试原因路由 | `_scope_feedback()` |
| 工具能力 | **必须隔离** | `SubagentSpec.allowed_tools` |
| 中间产物 | **必须隔离** | `NotRequired` 分支字段，不写回全局 |
| 资源预算 | 独立分配 | `ExecutionBudget` |

`analysis` 和 `writing` 的 `_HISTORY_SCOPE` 是 0，这是有意的：它们的输入应该来自 `dependency_results` 里已经检索、已经分析过的结构化结果，而不是原始对话。给它们全量历史只会增加 token 消耗并引入与当前任务无关的旧话题。

`search` 保留 6 条历史，因为多轮场景下用户会说"那它和上一个有什么区别"，指代消解必须依赖上下文。

### 15.2 权限三条硬规则

**规则一：权限在检索层前置过滤，不做后置过滤**

```text
错误：召回 top20 → 应用层过滤掉无权限的 → 剩 6 条
     问题一：top_k 被打穿，用户看到的结果变少且不可预测
     问题二：无权限文档的标题与摘要已经进过进程内存和日志

正确：权限条件编译进 ES query 的 filter 子句
     无权限文档在召回阶段就不存在
```

**规则二：权限上下文只能来自服务端可信来源**

```text
可信：会话、JWT claims、服务端查库得到的角色与关注关系
不可信：LLM 抽取的 user_id、Planner 输出的字段、工具调用参数里的身份
```

这条决定了 `Principal` 为什么必须 `frozen=True`。如果身份能被 LLM 影响，提示注入就是直接提权：用户在对话里声称"我是管理员"，模型照着填 `role="admin"`，权限体系当场失效。

**规则三：Subagent 权限只能继承或收窄**

```text
Main Agent 权限集合 ⊇ Subagent 权限集合
```

`dispatch_current_stage()` 只做透传和裁剪，从不构造或提升 `principal`。

### 15.3 检索层的权限注入

`RetrievalService.hybrid_search()` 需要接收 `principal` 并把权限条件编译进 filter：

```python
async def hybrid_search(
        self,
        semantic_queries: list[str],
        keywords: list[str],
        filters: ResolvedFilters,
        principal: Principal,
        exclude_doc_keys: list[str] | None = None,
        search_mode: str = "hybrid",
        top_k: int = 20,
) -> list[dict]:
    ...


def _build_permission_clauses(self, principal: Principal) -> list[dict]:
    """
    权限子句与业务筛选子句分开构造。

    业务筛选（标签、分类、时间）可以为空；
    权限子句永远非空，任何调用路径都不能绕过。
    """
    clauses: list[dict] = []

    # 管理员之外只能看到已发布内容
    if not principal.can_read_all_statuses():
        clauses.append({"term": {"status": "published"}})
    clauses.append({"term": {"is_deleted": False}})

    # 可见范围：public 或本人的内容
    visibility_should: list[dict] = []
    if "public" in principal.visible_scopes:
        visibility_should.append({"term": {"visibility": "public"}})
    if "own" in principal.visible_scopes:
        visibility_should.append({"term": {"user_id": principal.user_id}})

    if not visibility_should:
        # 宁可召回为空，也不允许退化成无条件查询
        visibility_should.append({"term": {"visibility": "__none__"}})

    clauses.append({"bool": {"should": visibility_should, "minimum_should_match": 1}})
    return clauses
```

关键细节：`visibility_should` 为空时插入一个必然匹配不到的条件，而不是省略该子句。**权限过滤缺失时的正确行为是零结果，不是全量结果。**

### 15.4 索引与回查也要闭环

ES 索引需要冗余权限字段，`article_vectors` 与 `article` 都要写入：

```text
status        published / draft / under_review
is_deleted    布尔
visibility    public / private / followers_only
user_id       作者，用于 own 范围判断
```

引用回查同样要校验，不能只在召回阶段过滤。`_enrich_cards_from_mysql` 的 SQL 需要补条件：

```sql
SELECT a.article_id, a.cover_image, a.view_count, a.like_count,
       u.nick_name AS author_name
FROM article_info a
LEFT JOIN user_info u ON a.user_id = u.user_id
WHERE a.article_id IN (:ids)
  AND a.status = 'published'
  AND a.is_deleted = 0
```

否则一旦离线索引链路漏删，草稿或已删除文章的封面、作者和阅读量仍会被渲染成前端卡片。**引用信息本身也是数据，泄漏路径不止正文一条。**

### 15.5 审计

每次检索记录结构化审计日志，字段至少包含：

```text
trace_id, run_id, task_id
principal.user_id, principal.role, principal.visible_scopes
执行的 filter 子句摘要
命中的 doc_key 列表
```

审计不是可选项：没有它，权限缺陷只能靠人工复现，无法回溯影响面。

---

## 十六、重试与重规划策略

### 16.1 前提：不改变检索条件的重试必然返回相同结果

向量检索是确定性的：同一个 query 经同一个 embedding 模型，在同一份索引上用同一组参数召回，结果一定完全一致。BM25 同理。

因此"再检索一次"本身没有意义。**重试必须改变输入。**

本架构的重试语义是 **replan**：Reflector 判定不通过时回边指向 Planner，`RESET_RESULTS_KEY` 清空 `task_results`，`current_stage_index` 归零，整个执行计划重新生成。

这比"同一个 Worker 带反馈重跑"力度更大，因为它能改变**任务结构**：

```text
第一轮：platform_search
重规划：platform_search + web_search        （增加检索路数）

第一轮：一个笼统的 search
重规划：拆成三个角度明确的 search           （分解检索意图）

第一轮：search → writing
重规划：search → analysis → writing         （补充中间环节）
```

### 16.2 replan 生效的三个必要条件

**条件一：Planner 的输入必须变化**

这是最容易漏的一点。如果 `staged_planner_node` 只读 `user_message` 和 `history_messages`，那么 replan 时输入与首次完全相同；配合 `temperature=0` 的结构化输出，会生成**逐字相同的计划**，整轮重试完全空转。

所以 `REPLAN_SUFFIX` 必须注入：上一轮任务列表、评审反馈、已尝试过的查询、已使用过的检索模式，并明确禁止重复上一轮的 `instruction`。同时把温度从 0 提到 0.4。

**条件二：已检索过的文档要能被排除**

`RESET_RESULTS_KEY` 清空了 `task_results`，如果检索足迹也一起丢掉，就连"上一轮召回了哪些文档"都不知道，无法去重。这就是 `retrieval_history` 使用独立 reducer 且不响应 reset 的原因。

检索层据此排除：

```python
def _build_exclude_clause(exclude_doc_keys: list[str]) -> dict | None:
    if not exclude_doc_keys:
        return None
    return {"terms": {"doc_key": exclude_doc_keys}}
```

放进 `bool.must_not`，让第二轮必然看到不同的候选集。

**条件三：反馈信号要对齐修复路径**

```text
错误：Reflector 只评最终回复质量 → 反馈"内容不够详细" → 重新检索
     问题：回复不好可能是生成环节的问题，用生成反馈驱动检索，方向是错的

正确：分开评估
     检索质量：关键实体是否被覆盖？召回数量与相关性分布如何？
     生成质量：是否忠实于证据？是否有幻觉？结构是否清晰？
```

### 16.3 Reflector 拆成两路判定

```python
class RetrievalQuality(BaseModel):
    coverage: int = Field(description="证据覆盖度 0-10：关键实体是否都有资料支撑")
    relevance: int = Field(description="证据相关性 0-10")
    passed: bool = Field(description="证据是否足以支撑回答")
    missing_aspects: list[str] = Field(default_factory=list, description="缺失的信息角度")


class GenerationQuality(BaseModel):
    faithfulness: int = Field(description="忠实度 0-10：是否只使用了给定证据")
    completeness: int = Field(description="完整性 0-10")
    formatting: int = Field(description="结构清晰度 0-10")
    passed: bool
    feedback: str = ""
```

路由规则：

```python
def route_after_reflector(state: StagedAgentState) -> str:
    if not state.get("needs_retry"):
        return "synthesize"

    budget = state.get("budget", {})
    if state.get("retry_count", 0) >= budget.get("max_replans", 1):
        return "synthesize"          # 预算用尽，带着现有结果收尾

    if state.get("retry_reason") == "retrieval":
        return "replan"              # 证据不足，重新规划检索
    return "regenerate"              # 证据够但表达差，只重跑生成
```

`regenerate` 直接回到 `prepare_results` 之后重新合成，**不重跑检索**。这避免了最常见的浪费：为了改一个格式问题，把整条检索链路重新执行一遍。

判定检索是否命中优先使用确定性信号，而不是让模型猜：

```python
def has_retrieval_evidence(task_results: dict[str, dict]) -> bool:
    """有确定性信号时不要交给 LLM 判断。"""
    return any(
        result.get("retrieved_count", 0) > 0
        for result in task_results.values()
        if result.get("subagent") == "search"
    )
```

`retrieved_count == 0` 是事实，不需要评审模型确认。

### 16.4 无进展检测

只有次数上限不够。如果两轮召回的是同一批文档，继续重试没有意义：

```python
JACCARD_STALL_THRESHOLD = 0.8


def is_stalled(previous_keys: set[str], current_keys: set[str]) -> bool:
    """
    候选集重合度过高说明当前策略无效，
    应该直接降级而不是继续消耗预算。
    """
    if not previous_keys or not current_keys:
        return False
    intersection = len(previous_keys & current_keys)
    union = len(previous_keys | current_keys)
    return union > 0 and intersection / union >= JACCARD_STALL_THRESHOLD
```

命中无进展时的正确动作是**降级而不是重试**：

```text
1. 升级检索范围：站内无结果 → 强制 web_search 兜底
2. 放宽检索参数：提高 top_k、降低相似度阈值、切换 BM25
3. 明确告知不足：回答"知识库中没有相关内容"，禁止编造
```

第三条是底线。**检索失败时最差的处理是让模型凭常识补全**，那等于用幻觉换取一个看起来完整的回答。

### 16.5 防止重试放大

阶段化架构下重试成本是乘性增长的：

```text
一次 replan 生成 4 个 Task
每个 Task 内部允许 4 次工具调用
每次检索发起 3 条语义查询 + 4 个关键词

单轮最坏：4 × 4 × 7 = 112 次下游调用
```

所以 `ExecutionBudget` 必须同时约束多个维度，而不只是重试次数：

```python
class ExecutionBudget(BaseModel):
    max_replans: int = 1
    max_tool_calls_per_task: int = 4
    max_total_tasks: int = 12
    deadline_ts: float | None = None
```

`deadline_ts` 是最后一道闸门：无论其他计数是否用尽，超过截止时间立即收尾，用已有结果生成回答。

### 16.6 与主流方案的对应关系

| 方案 | 核心思路 | 本架构对应 |
|---|---|---|
| Self-RAG | 模型自评检索必要性与证据充分性 | Reflector 的 `RetrievalQuality` |
| CRAG | 检索质量分级，低质时触发查询改写或联网 | `retry_reason="retrieval"` → replan，无进展则升级 web |
| Query Decomposition | 复杂问题拆多个子查询 | Planner 在 replan 时把一个 search 拆成多个 Task |
| Corrective 去重 | 排除已验证无效的证据 | `retrieval_history.seen_doc_keys` → `must_not` |

差别在于：主流实现多数把这些逻辑放在 RAG 链路内部，本架构把**结构级修正**上提到了 Planner，把**策略级修正**留在 Search Subagent 内部。前者能改变任务图，后者只能改变查询。

---

## 十七、面试回答

### 简洁版

> 当前 Planner 输出的是扁平 `active_workers`，Dispatcher 使用 LangGraph Send API 将 Worker 放在同一个 superstep 并行执行。同一 superstep 的 Worker 读取的是相同 State 快照，结果只有本轮结束后才通过 reducer 合并，因此 Analysis 无法读取同批 Search 的结果。后续我计划演进为 Main Agent + Subagent：Planner 输出 Task 及 dependsOn，后端通过拓扑排序自动划分 Stage；阶段内 Subagent 并行，StageBarrier 汇合结果后再串行推进下一阶段，从而同时保证并行性能和任务依赖正确性。

### 深入版关键点

1. Superstep 是一轮并行计算，节点更新在本轮结束后才可见。
2. Barrier 是 fan-in 节点，不是线程锁或主动轮询。
3. Planner 负责语义任务拆解，确定性代码负责拓扑排序和环检测。
4. 同 Stage 只允许无依赖任务并行。
5. 下一 Stage 按 `depends_on` 精确注入前序结果。
6. Task 结果以 taskId 存储，避免同类型 Subagent 多任务无法区分。
7. 写作生成、HITL 审批和保存副作用应拆成不同节点。
8. 当前扁平并行已经实现，阶段化架构属于后续改造方案。

### 追问一：RAG 是谁调用的？主 Agent 自己调，还是让子 Agent 去检索？

> 我的划分是意图和策略分层：Main Agent 决定要不要检索、检索几路、每路检索什么，产出的是带 `depends_on` 的 Task 列表；具体怎么检索由 Search Subagent 决定，它内部完成查询改写、混合召回、RRF 融合、重排和引用构建。Main Agent 不感知 chunk、embedding 这些细节。
>
> 这样分的核心原因是上下文隔离。粗检索会产出几十条候选、上千 token 的原文片段，还有被重排丢弃的结果和相似度分数。这些如果进入 Main Agent 的窗口，会挤占预算并干扰后续规划。Subagent 在自己的窗口里消化完，只回传压缩后的内容和引用编号。
>
> 有个反模式我特意避开了：同一次请求里既做前置检索、又把检索工具暴露给同一个 LLM。这不只是重复消耗，更麻烦的是两条路径的证据质量不同——前置链路有改写和重排、带引用编号，工具那条是裸召回、没有引用，模型无法区分，可能用更差的结果覆盖更好的。所以我的 Subagent 工具白名单里，`search` 只有 `web_search` 和 `get_trending_topics`，站内检索工具被摘掉了，站内 RAG 只能走 Subagent 内部的确定性链路。检索入口必须唯一。

### 追问二：主子 Agent 之间的文档权限怎么判断？上下文是否一致？

> 上下文我是按层处理的，不是简单的一致或隔离。
>
> 必须完全一致且不可篡改的是身份与权限：State 里放一个 `Principal` 对象，包含 user_id、role 和可见范围，`frozen=True`，由服务端在请求入口从会话构造，逐分支透传。绝不允许来自 LLM 输出、Planner 生成或工具参数——因为一旦身份能被模型影响，提示注入就是直接提权，用户在对话里声称自己是管理员，模型照着填，权限体系当场失效。
>
> 必须隔离的是工具能力和中间产物。每个 Subagent 有独立的工具白名单，只换 System Prompt 不换工具，等于每个子 Agent 都持有全量能力，职责边界形同虚设。中间产物用 `NotRequired` 的分支字段承载，不写回全局，并行 Subagent 看不到彼此的执行过程。
>
> 需要精确裁剪的是数据上下文。依赖结果只注入 `depends_on` 声明的那几个任务，不是整个 `task_results`；对话历史按 Subagent 需求给，search 需要历史做指代消解所以给 6 条，analysis 和 writing 不给，因为它们的输入应该来自结构化的前序结果而不是原始对话。反馈信号也按重试原因路由，检索没命中就不要把"文章结构不清晰"传给 search。
>
> 文档权限我遵守三条硬规则。第一，权限条件必须编译进 ES query 的 filter 子句做前置过滤，不做后置过滤——后置会打穿 top_k，而且无权限文档的标题摘要已经进过内存和日志。第二，权限上下文只能来自服务端可信来源。第三，Subagent 权限只能继承或收窄，调度层只做透传和裁剪，从不构造或提升 principal。
>
> 有两个细节容易漏：一是权限过滤缺失时的正确行为是返回零结果而不是全量结果，所以可见范围为空时我插入一个必然匹配不到的条件，而不是省略该子句；二是引用回查 MySQL 补元数据时也要带状态过滤，因为引用信息本身也是数据，泄漏路径不止正文一条——离线索引一旦漏删，草稿文章的封面和作者仍会被渲染成前端卡片。

### 追问三：第一次 RAG 结果不对，Agent 再调一次会不会返回同样的结果？

> 如果只是用同一个查询再调一次，一定返回完全相同的结果。向量检索是确定性的，同 query 经同一个 embedding 模型在同一份索引上用同一组参数召回，结果逐条相同，BM25 也一样。所以重试必须改变输入才有意义。
>
> 我的架构里重试语义是重规划而不是重检索：Reflector 判定不通过时回边指向 Planner，清空 task_results、stage_index 归零，整个执行计划重新生成。这样重试能改变任务结构——原来只有站内检索可以加一路联网，一个笼统的检索任务可以拆成几个角度明确的子任务，资料零散时还能插入一个 analysis 环节。这比只改写 query 的力度大得多。
>
> 但要让重规划真正生效，有三个必要条件。
>
> 第一，Planner 的输入必须变。这是我第一版设计里的实际缺陷：Planner 只读 user_message 和历史消息，重规划时输入和首次完全一样，配合 temperature=0 的结构化输出会生成逐字相同的计划，整轮重试完全空转。修法是注入上一轮任务列表、评审反馈、已尝试过的查询和检索模式，明确禁止重复上一轮的 instruction，同时把温度从 0 提到 0.4。
>
> 第二，已检索过的文档要能被排除。重规划会清空任务结果，如果检索足迹一起丢掉，就连上一轮召回了什么都不知道。所以我用一个独立的 `retrieval_history` 字段，配单独的 reducer，故意不响应重置标记，跨轮累积 doc_key 和查询记录，下一轮放进 `bool.must_not` 强制看到不同候选集。
>
> 第三，反馈信号要对齐修复路径。我把 Reflector 拆成检索质量和生成质量两路：证据不足才重规划，证据够但表达差只重跑合成、不重跑检索。而且判定检索是否命中优先用确定性信号——`retrieved_count == 0` 是事实，不需要交给评审模型猜。
>
> 终止条件除了次数上限，我还加了无进展检测：如果两轮召回的候选集 Jaccard 相似度超过 0.8，说明当前策略无效，此时正确动作是降级而不是继续重试。降级路径是先强制联网兜底，再放宽检索参数，最后明确回答"知识库里没有相关内容"。最后这条是底线，检索失败时最差的处理是让模型凭常识补全，那等于用幻觉换一个看起来完整的回答。
>
> 阶段化架构下还要特别防重试放大。一次重规划可能生成 4 个 Task，每个 Task 允许 4 次工具调用，每次检索发起 3 条语义查询加 4 个关键词，单轮最坏是上百次下游调用。所以预算要同时约束重规划次数、单任务工具调用数、总任务数和截止时间，其中截止时间是最后一道闸门。

### 追问四：为什么不让主 Agent 直接输出 Stage？

> 因为拓扑排序是确定性问题，不该交给概率模型。让模型直接输出 Stage，它可能把有依赖关系的任务放进同一阶段——比如把 analysis 和它依赖的 search 放在一起并行，那分析节点拿到的就是空资料。
>
> 我的做法是 Planner 只输出 Task 和 `depends_on`，由代码执行校验、环检测和 Kahn 分层。这样能可靠拦住重复 task_id、依赖不存在的任务、自依赖和循环依赖，还能用不同的并发上限对同一份依赖计划重新分层。边界很清晰：模型负责语义理解，代码负责执行正确性。

### 已知偏差声明

面试时如实说明当前状态，不要把设计方案说成已上线实现：

- 阶段化调度尚未落地，运行代码仍是 Planner 输出扁平 Worker 列表 + Dispatcher 同阶段并行。
- 权限过滤尚未接入检索层，`RetrievalService` 当前只有标签、分类、作者、时间等业务筛选条件。
- 工具白名单尚未生效，Worker 内部仍使用 `tool_registry.get_all_tools()`。
- `QueryRewriteService.rewrite()` 返回 dict 时漏了 `filters`、`search_mode`、`need_web_search` 三个字段，导致 `search_worker` 读取 `rewrite_result["filters"]` 会抛 KeyError，联网决策也从未生效。
- `EsVectorStore.search()` 与 `EsComponent.search()` 签名不含 `filters` 参数，`RetrievalService` 构造的 filter 子句目前传不下去。
- `RetrievalService` 中调用的 `_normalize_vector_hit`、`_normalize_keyword_hit`、`_build_keyword_filter` 与实际定义的 `_normalize_vector_int`、`_normalize_article_hit`、`_build_article_filter` 不一致。
- `search_worker` 中 `citation_builder_instance` 未定义。

能讲清设计意图和每层职责，同时准确指出哪些还没打通，比声称全部已完成更可信。


---

## 十八、Task 结果保存、跨轮复用与依赖注入（最终口径）

> 本节是对 9.3、9.5 和第十六节的生产化补充与修正。前文的单层 `task_results` 与 `RESET_RESULTS_KEY` 可以继续作为“当前计划轮次的工作区”，但不能再被理解为所有历史结果的唯一存储。涉及多轮重规划、证据复用和依赖注入时，以本节为准。
>
> 本节仍属于目标架构设计，尚未写入 `python-agent` 运行代码。

### 18.1 保存单位是 Task，不是 Subagent

同一个 Subagent 可以在同一 Stage 或不同 Stage 中执行多个 Task：

```text
Search Subagent
├─ T1：搜索 Spring 事务资料
├─ T2：搜索 MyBatis 缓存资料
└─ T3：搜索数据库隔离级别资料
```

如果按 `subagent="search"` 保存，多个任务会覆盖或混在一起，后序任务也无法通过 `depends_on` 精确定位结果。因此结果的主索引必须是：

```text
request_id + plan_attempt + task_id
```

层级关系如下：

```text
conversation_id
└─ request_id                  一次用户请求
   ├─ plan_attempt = 1         初始计划
   │  ├─ task_id = T1
   │  └─ task_id = T2
   └─ plan_attempt = 2         L3a 触发的第二轮计划
      ├─ task_id = T3
      └─ task_id = T4
```

字段职责：

| 字段 | 含义 |
|---|---|
| `conversation_id` | 多轮对话所属会话 |
| `request_id` | 当前这一条用户请求，对应一次完整 Agent run |
| `plan_attempt` | 同一请求内部第几轮计划，初始为 1 |
| `task_id` | 当前计划中的任务标识，是依赖解析的主键 |
| `subagent` | 执行该 Task 的能力类型，只是元数据，不作为结果主键 |

多轮对话与多轮重规划不能混淆：

```text
多轮对话：conversation_id 相同，request_id 不同
多轮重规划：request_id 相同，plan_attempt 不同
```

### 18.2 TaskResult 契约

每个 Task 最终只向 Main Agent 提交一份确定结果：

```python
from typing import Literal

from pydantic import BaseModel, Field


class TaskResult(BaseModel):
    request_id: str
    plan_attempt: int
    task_id: str
    subagent: Literal["search", "analysis", "writing", "chat"]
    stage_index: int

    status: Literal[
        "success",
        "empty",
        "failed",
        "skipped",
        "cancelled",
        "invalidated",
    ]
    content: str = ""

    # Search 类结果使用；其他 Subagent 保持默认值。
    retrieved_count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)

    # 精确记录派生关系，便于依赖失效与审计。
    dependency_task_ids: list[str] = Field(default_factory=list)

    error_type: str | None = None
    error_message: str | None = None
    local_retry_count: int = 0
```

`plan_attempt` 和 `local_retry_count` 表示两种不同循环：

```text
plan_attempt：L3a 回到 Planner，任务图发生变化
local_retry_count：Subagent 内部对同一 Task 做一次参数级自愈
```

例如 Search 第一次用 vector 召回为空，切换 keyword 后成功，这仍然只产生一个 `TaskResult`：

```json
{
  "plan_attempt": 1,
  "task_id": "T1",
  "subagent": "search",
  "status": "success",
  "retrieved_count": 5,
  "local_retry_count": 1
}
```

两次内部尝试可以记录在 trace 或观测系统中，但不能向全局 State 提交两份同 ID 的结果，否则下游无法判断哪一份是最终结果。

### 18.3 State 使用“当前轮工作区 + 跨轮归档 + 证据池”

推荐把状态拆成四个相互独立的区域：

```python
class StagedAgentState(TypedDict):
    request_id: str
    plan_attempt: int

    # 当前 plan_attempt 的工作区。现有 9.3、9.5、9.6 中的 task_results
    # 都应按这个语义理解；并行分支只向这里提交本 Task 的最终结果。
    task_results: Annotated[dict[str, dict], merge_task_results]

    # 外层 key 是 plan_attempt，内层 key 是 task_id。
    # 旧轮次只读，用于审计、回放和判断哪些派生结果已经失效。
    task_results_by_attempt: dict[int, dict[str, dict]]

    # 跨轮复用的原始证据，按 doc_key/evidence_id 去重。
    evidence_pool: dict[str, dict]

    # 查询、检索模式和候选文档足迹，用于避免原样重复与无进展检测。
    retrieval_history: Annotated[dict, merge_retrieval_history]
```

示例：

```python
task_results_by_attempt = {
    1: {
        "T1": spring_search_result,
        "T2": mybatis_empty_result,
    },
    2: {
        "T3": mybatis_supplement_result,
        "T4": new_analysis_result,
    },
}
```

读取第一轮 T1：

```python
result = task_results_by_attempt[1]["T1"]
```

`subagent` 只是 `TaskResult` 的属性。如需按 Subagent 统计耗时或成功率，可以从 TaskResult 派生分组视图，但不能把“一个 Agent 一个集合”作为事实存储模型。

### 18.4 并行结果如何合并和归档

同一 Stage 中，每个 `Send` 分支只返回自己的一项：

```python
# T1 分支
return {"task_results": {"T1": result_t1}}

# T2 分支
return {"task_results": {"T2": result_t2}}
```

`merge_task_results` 在 superstep 结束时合并为：

```python
{
    "T1": result_t1,
    "T2": result_t2,
}
```

Reducer 必须拒绝同一轮重复 `task_id`，不能使用“后写覆盖前写”：

```python
def merge_task_results(current: dict, update: dict) -> dict:
    duplicate_ids = current.keys() & update.keys()
    if duplicate_ids:
        raise ValueError(f"任务结果重复: {sorted(duplicate_ids)}")
    return {**current, **update}
```

计划轮次结束后，由一个确定性单节点归档当前工作区。归档动作不能由并行 Subagent 自己执行：

```python
def archive_current_attempt(state: StagedAgentState) -> dict:
    attempt = state["plan_attempt"]
    archives = dict(state.get("task_results_by_attempt", {}))

    if attempt in archives:
        raise ValueError(f"plan_attempt={attempt} 已经归档")

    archives[attempt] = dict(state.get("task_results", {}))
    return {"task_results_by_attempt": archives}
```

如果 L3a 决定 replan，顺序必须是：

```text
归档当前 task_results
    ↓
保留 evidence_pool / retrieval_history / retry budget
    ↓
plan_attempt += 1
    ↓
清空的只是当前轮工作区 task_results
    ↓
进入 Planner 生成下一轮计划
```

因此前文的 `RESET_RESULTS_KEY` 只允许清空**当前工作区**，不能删除 `task_results_by_attempt`、`evidence_pool` 或 `retrieval_history`。

### 18.5 Subagent 如何获得依赖结果

Subagent 不主动查询全局 State，也不提供可由模型任意调用的 `get_task_result(task_id)` 工具。完整流程是：

```text
Planner 在 Task 中声明 depends_on
    ↓
后端校验 DAG、做拓扑分层
    ↓
StageDispatcher 取得当前 Task 的依赖 ID
    ↓
从当前 plan_attempt 的 task_results 精确查找
    ↓
检查依赖是否存在且状态可用
    ↓
ContextBuilder 只注入这些依赖结果和对应证据
    ↓
调用目标 Subagent
```

例如：

```json
{
  "task_id": "T3",
  "subagent": "analysis",
  "instruction": "对比 Spring 和 MyBatis",
  "depends_on": ["T1", "T2"]
}
```

后端解析器：

```python
class MissingDependencyError(RuntimeError):
    pass


class UnavailableDependencyError(RuntimeError):
    pass


def resolve_dependency_results(
    state: StagedAgentState,
    task: dict,
) -> dict[str, dict]:
    current_results = state.get("task_results", {})
    resolved: dict[str, dict] = {}

    for dependency_id in task.get("depends_on", []):
        result = current_results.get(dependency_id)
        if result is None:
            # 任务完全缺席属于图、Reducer 或节点实现错误，不能让模型补救。
            raise MissingDependencyError(
                f"任务 {task['task_id']} 缺少依赖 {dependency_id}"
            )

        if result.get("status") != "success":
            # failed/empty/skipped 要由 Barrier 与 L3a 分类，当前 Task 不应启动。
            raise UnavailableDependencyError(
                f"任务 {task['task_id']} 的依赖 {dependency_id} "
                f"状态为 {result.get('status')}"
            )

        resolved[dependency_id] = result

    return resolved
```

推荐把 `dependency_results` 定义为 `task_id -> TaskResult` 字典，而不是无键列表，这样 Prompt、日志和异常都能保留来源：

```python
class SubagentInput(BaseModel):
    current_task: dict
    dependency_results: dict[str, TaskResult]
    dependency_evidence: list[dict]
    history_messages: list[dict]
```

Dispatcher 注入的证据由两部分组成：当前轮依赖任务产出的 `evidence_ids`，以及增量重规划控制器显式选择的 `carried_evidence_ids`。后者不是让 Planner 或 Subagent任意读取整个证据池，而是由后端根据上一轮已经通过权限与相关性校验的 active evidence 生成，并再次验证存在性和当前 Principal 权限。

```python
dependency_results = resolve_dependency_results(state, task)

dependency_evidence_ids = {
    evidence_id
    for result in dependency_results.values()
    for evidence_id in result.get("evidence_ids", [])
}
carried_evidence_ids = set(task.get("carried_evidence_ids", []))
evidence_ids = dependency_evidence_ids | carried_evidence_ids

missing_evidence_ids = evidence_ids - state.get("evidence_pool", {}).keys()
if missing_evidence_ids:
    raise MissingDependencyError(
        f"任务 {task['task_id']} 引用了不存在的证据: "
        f"{sorted(missing_evidence_ids)}"
    )

# 真实实现还必须在这里按当前 Principal 重新校验证据可见性。
subagent_input = {
    "current_task": task,
    "dependency_results": dependency_results,
    "dependency_evidence": [
        state["evidence_pool"][evidence_id]
        for evidence_id in evidence_ids
    ],
    "history_messages": _scope_history(
        state.get("history_messages", []),
        task["subagent"],
    ),
}
```

因此第 18.9 节第二轮的 T4 除了 `depends_on=["T3"]`，还应由后端写入 `carried_evidence_ids=["E1", "E2", "E3"]`；其最终证据输入才是第一轮保留的 E1～E3 与本轮 T3 产出的 E4、E5 的并集。

这里有三条硬规则：

1. 同 Stage 中的任务相互独立，不能读取彼此尚未提交的结果；只有下一 Stage 才能读取已通过 Barrier 的结果。
2. Analysis/Writing 只得到 `depends_on` 声明的结果和对应证据，不广播整个 `task_results`。
3. `principal`、工具白名单和预算属于可信 Runtime Context，不允许依赖结果覆盖这些控制字段。

如果依赖不存在或不可用，不能把空上下文交给 Subagent，让它凭训练知识补全：

```text
依赖完全缺席          → 结构不变量失败，fail-fast
依赖 status=failed    → Barrier 分类基础设施故障，关键任务则交 L3a
依赖 status=empty     → Barrier 分类证据缺失，关键任务则交 L3a
依赖全部 success      → 才允许启动下游 Task
```

### 18.6 跨 plan_attempt 的依赖与证据复用

裸 `task_id` 只在当前计划轮次内唯一。若必须引用历史 Task，必须使用完整引用：

```python
class TaskRef(BaseModel):
    plan_attempt: int
    task_id: str
```

但默认不建议第二轮直接依赖第一轮的 Analysis/Writing。更稳妥的规则是：

```text
跨轮复用原始证据 evidence_pool
当前轮重新生成依赖这些证据的 Analysis/Writing
```

原因是旧 Analysis/Writing 只见过旧证据，新证据加入后它们已经过期。跨轮增量重规划时的数据处理如下：

| 数据 | 第二轮处理 |
|---|---|
| 第一轮有效 Search 证据 | 保留并加入 `evidence_pool` |
| 第一轮查询和 doc_key 足迹 | 保留在 `retrieval_history` |
| 第一轮 TaskResult | 保留在 `task_results_by_attempt[1]`，只读审计 |
| 第一轮 Analysis/Writing | 标记为旧轮次或 `invalidated`，不进入当前合成 |
| 第二轮补充证据 | 与第一轮证据按 `evidence_id/doc_key` 去重合并 |
| 最终 Analysis/Writing | 使用两轮有效证据重新生成 |

示例：

```text
第一轮证据：E1 Spring 原理、E2 Spring 失效、E3 MyBatis 原理
EvidenceGate：缺少 MyBatis 缓存失效场景

第二轮只新增：
T4 搜索 flushCache、commit/rollback 对缓存的影响
    ↓ 得到 E4、E5

evidence_pool = E1 + E2 + E3 + E4 + E5
    ↓
重新执行 Analysis
    ↓
重新执行 Writing
```

第二轮不是默认推翻第一轮，而是补充 `missing_aspects`。只有第一轮意图理解完全错误、证据整体不相关或权限已经变化时，才做全量 replan，并把旧证据从 active evidence 中移除。

为了节省 Token，Planner 只接收：

```text
已覆盖的 aspect 摘要
缺失的 missing_aspects
已试 query / search mode
上一轮计划摘要
```

不把 `evidence_pool` 的全部原文 Chunk 塞进 Planner。原文只在真正需要证据的 Analysis/Writing 分支中按需注入。

### 18.7 EvidencePool 与派生结果失效

`evidence_pool` 保存的是经过权限过滤、基础相关性校验且仍可复用的原始证据：

```python
class EvidenceItem(BaseModel):
    evidence_id: str
    doc_key: str
    article_id: int | None = None
    title: str
    content: str
    source: Literal["platform", "web"]
    aspect_ids: list[str] = Field(default_factory=list)
    first_seen_attempt: int
```

证据池按 `doc_key` 或稳定 `evidence_id` 去重。第二轮补充检索可以对 `retrieval_history.seen_doc_keys` 使用 `must_not` 强制寻找新候选，但旧证据仍保留在 `evidence_pool` 中参与最终分析。

派生结果失效遵循依赖传播：

```text
E1、E2、E3 → Analysis A1 → Writing W1
新增 E4、E5
             ↓
A1 未见过 E4、E5，因此失效
W1 依赖 A1，因此也失效
             ↓
E1～E5 → Analysis A2 → Writing W2
```

“失效”默认是逻辑失效而不是物理删除：旧结果仍保存在归档中，但最终合成只选择当前计划的有效结果。若 Writing 已经产生数据库草稿：

- 尚未审批的草稿：更新同一草稿版本或生成新 revision，旧版本保留审计。
- 已审批或已发布内容：禁止自动覆盖或删除，必须创建新 revision 并再次进入 HITL。

证据跨轮复用前仍需按当前 `Principal` 重新验证可见性；Redis 中曾经保存过不代表当前用户仍然有权读取。

### 18.8 Redis Checkpointer 与业务归档不是一回事

Redis Checkpointer 会在图节点结束后持久化 State 快照，用于中断恢复和故障恢复，但它不会自动决定：

```text
哪些旧 TaskResult 仍然有效
哪些证据可以跨轮复用
哪些 Analysis/Writing 因依赖变化而失效
下一轮应该注入哪些结果
```

这些语义必须由 `task_results_by_attempt`、`evidence_pool`、`retrieval_history` 和依赖失效规则显式表达。

如果需要长期审计，可以在 MySQL 设计：

```text
agent_run
  request_id, conversation_id, status, created_at

agent_plan_attempt
  request_id, plan_attempt, plan_json, status

agent_task_result
  request_id, plan_attempt, task_id, subagent, status, result_json

agent_evidence
  request_id, evidence_id, doc_key, source, metadata_json
```

Redis负责运行时快照，MySQL负责长期审计；二者不能互相替代。

### 18.9 端到端示例

```text
用户：对比 Spring 事务和 MyBatis 缓存，并写成文章

request_id=req_1001
plan_attempt=1

Stage 0
  T1 Search(Spring)  → success, evidence=[E1,E2]
  T2 Search(MyBatis) → success, evidence=[E3]

Reducer
  task_results={T1: result1, T2: result2}

Barrier
  T1、T2 齐全且成功

Main Agent EvidenceGate
  已覆盖：Spring 原理、Spring 失效、MyBatis 原理
  缺失：MyBatis 缓存失效
  → 归档 task_results_by_attempt[1]
  → plan_attempt=2
  → 保留 evidence_pool={E1,E2,E3}
  → 回 Planner 做增量重规划

plan_attempt=2

Stage 0
  T3 Search(MyBatis 缓存失效) → success, evidence=[E4,E5]

EvidencePool
  {E1,E2,E3} + {E4,E5} → {E1,E2,E3,E4,E5}

Stage 1
  T4 Analysis
  depends_on=[T3]
  carried_evidence_ids=[E1,E2,E3]
  dependency_results={T3: result3}
  dependency_evidence=[E1,E2,E3,E4,E5]
  → 生成 A2

Stage 2
  T5 Writing
  dependency_results={T4: result4}
  → 生成 W2

最终合成
  只读取当前有效的 A2/W2
  第一轮 TaskResult 保留审计，但不把旧派生结果混入最终回复
```

### 18.10 当前实现偏差

当前运行代码仍是：

```text
Planner 输出 active_workers + task_descriptions
Dispatcher 按 worker_name 分发
worker_results 使用 list + add reducer
同一 Worker 一轮只能表达一个任务
没有 task_id / depends_on / plan_attempt
没有 task_results_by_attempt / evidence_pool
Worker 读取较宽的全局 State，而不是由 ContextBuilder 精确注入依赖
```

因此本节描述的是目标实现，不能在简历或面试中表述为已经上线。实施时建议按以下顺序演进：

```text
1. 引入 Task、task_id、depends_on 和拓扑分层
2. 将当前轮结果改为 task_id -> TaskResult
3. StageDispatcher 实现依赖解析与最小上下文注入
4. 增加 plan_attempt 与 task_results_by_attempt 归档
5. 增加 evidence_pool 与跨轮增量 replan
6. 增加派生结果失效和草稿版本控制
```
