# Multi-Agent Worker 扩展与规范指南

## 一、架构总览

```
用户 → Planner(LLM) → Dispatcher(Send API 并行) → Worker 节点们 → Synthesizer(LLM 流式)
```

**核心设计决策**：选择 Multi-Agent Graph 而非 ReAct/Skill 模式的原因：
- ReAct：单 LLM 循环，不支持并行，流程不可控
- Skill-as-Tool：本质是 ReAct + 大粒度 Tool，无法做审批流
- **Multi-Agent Graph**：支持并行调度、Human-in-the-Loop、流式进度推送、流程可编排

---

## 二、已完成的规范化改造

### 2.1 公共 Tool 调用循环：`tool_executor.py`

**问题**：search_worker / writing_worker / analysis_worker 都有一段几乎相同的代码：
```python
llm_with_tools = llm.bind_tools(tools)
for round_num in range(MAX_ROUNDS):
    response = await llm_with_tools.ainvoke(messages)
    if not response.tool_calls:
        break
    for tool_call in response.tool_calls:
        ...
```

**方案**：抽到 `app/graph/tool_executor.py` → `run_tool_agent()` 函数。

改造后，每个 Worker 的 Tool 调用只需一行：
```python
result = await run_tool_agent(
    system_prompt=MY_PROMPT,
    user_input=task_input,
    tools=AVAILABLE_TOOLS,
    max_rounds=2,
)
```

### 2.2 改造后的 Worker 代码量对比

| Worker | 改造前（行数） | 改造后（行数） | 减少 |
|--------|------------|------------|------|
| analysis_worker | 69 | 42 | -39% |
| writing_worker | 107 | 66 | -38% |
| search_worker | 189 | ~170 | -10%（RAG 逻辑本身不重复） |

### 2.3 修复的 Bug

`analysis_worker.py` 原来的 `return` 写在 `for` 循环内，只会执行一轮 Tool 调用就返回。

---

## 三、新增 Worker 的标准流程

以新增一个 **翻译 Worker** 为例：

### 第 1 步：创建 Worker 文件

```python
# app/graph/nodes/translate_worker.py

from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
from app.tools.web_search import web_search

AVAILABLE_TOOLS = [web_search]  # 翻译可能需要联网查术语

TRANSLATE_SYSTEM_PROMPT = """你是一个专业的技术翻译助手。
将用户提供的内容翻译为目标语言，保持技术术语准确。
如果遇到不确定的术语，使用 web_search 查询标准翻译。"""


async def translate_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("translate", state["user_message"])

    result = await run_tool_agent(
        system_prompt=TRANSLATE_SYSTEM_PROMPT,
        user_input=task_input,
        tools=AVAILABLE_TOOLS,
        max_rounds=1,
    )

    return {
        "worker_results": [{
            "worker_name": "translate",
            "result": result,
        }]
    }
```

### 第 2 步：注册到图（builder.py）

```python
from app.graph.nodes.translate_worker import translate_worker_node

# add_node
graph.add_node("translate_worker", translate_worker_node)

# add_edge
graph.add_edge("translate_worker", "synthesizer")
```

### 第 3 步：Dispatcher 加分支

```python
# dispatcher.py
elif worker == "translate":
    sends.append(Send("translate_worker", state))
```

### 第 4 步：Planner prompt 加描述

```python
# planner.py 的 PLANNER_SYSTEM_PROMPT
- translate: 翻译专家，负责中英文互译、技术文档翻译
```

### 第 5 步：前端进度映射（可选）

```python
# main.py 的 NODE_TO_PROGRESS
"translate_worker": "translate",
```

**总共改 4 个文件，每处改动 1-2 行。**

---

## 四、Worker 编写规范

### 4.1 标准模板

```python
"""
[Worker 名称] 节点
"""
from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
# 按需导入 Tool

AVAILABLE_TOOLS = [...]  # 该 Worker 可用的工具

XXX_SYSTEM_PROMPT = """..."""


async def xxx_worker_node(state: AgentState) -> dict:
    # 1. 检查取消
    if state.get("cancelled"):
        return {"worker_results": []}

    # 2. 获取任务输入
    task_input = state["task_descriptions"].get("xxx", state["user_message"])

    # 3. 执行（如有特殊逻辑在这里加，如 RAG 检索、interrupt 等）
    result = await run_tool_agent(
        system_prompt=XXX_SYSTEM_PROMPT,
        user_input=task_input,
        tools=AVAILABLE_TOOLS,
        max_rounds=2,
    )

    # 4. 返回标准格式
    return {
        "worker_results": [{
            "worker_name": "xxx",
            "result": result,
        }]
    }
```

### 4.2 规范要点

| 规则 | 说明 |
|------|------|
| **函数名** | `xxx_worker_node`，与文件名一致 |
| **返回格式** | 必须包含 `worker_results` 列表 |
| **取消检查** | 第一行检查 `state.get("cancelled")` |
| **任务输入** | 从 `task_descriptions` 取，fallback 到 `user_message` |
| **Tool 调用** | 统一用 `run_tool_agent`，不要自己写循环 |
| **旁路数据** | 如 article_cards，直接加到返回 dict 中 |
| **interrupt** | 只有需要审批的 Worker 才用，如 writing_worker |

---

## 五、项目文件结构

```
app/
├── config.py                    # 配置 + LLM 工厂
├── main.py                      # FastAPI 入口 + SSE 流式
├── clients/
│   ├── es_client.py             # Elasticsearch（向量 + 全文）
│   ├── redis_client.py          # Redis（会话缓存）
│   └── mysql_client.py          # MySQL（会话持久化）
├── graph/
│   ├── state.py                 # AgentState 定义
│   ├── builder.py               # 图构建 + Checkpointer
│   ├── tool_executor.py         # ★ 公共 Tool 调用循环
│   └── nodes/
│       ├── planner.py           # 意图识别 + 任务分解
│       ├── dispatcher.py        # Send API 并行调度
│       ├── search_worker.py     # RAG 两阶段检索
│       ├── chat_worker.py       # 日常对话
│       ├── analysis_worker.py   # 数据分析
│       ├── writing_worker.py    # 写作 + interrupt
│       └── synthesizer.py       # 结果汇总（流式输出）
├── services/
│   ├── conversation.py          # 会话管理（MySQL + Redis + 摘要压缩）
│   ├── query_rewrite.py         # 查询改写
│   ├── reranker.py              # Reranker 精排
│   ├── embedding.py             # ZhipuAI Embedding
│   └── image_understanding.py   # GLM-4V 图片理解
└── tools/
    ├── web_search.py            # @tool 联网搜索（博查）
    └── article_tool.py          # @tool 文章搜索（ES）
```
