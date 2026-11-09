# Skill 自发现 + 两阶段选择模式

## 一、什么是 Skill

Skill 是比 Tool 更大粒度的能力封装。

```
Tool  = 原子操作（一个函数：搜索、调 API、查数据库）
Skill = 完整工作流（可能包含多个 Tool + Prompt + 决策逻辑）
```

**类比**：
- Tool 是「螺丝刀」，Skill 是「修电脑」（需要螺丝刀+万用表+经验判断）
- `@tool web_search` 是 Tool
- 「RAG 两阶段检索」是 Skill（查询改写 → 多路召回 → 精排 → LLM 判断是否联网补充）

## 二、Skill 的两种运行模式

### 模式 A：ReAct（单 Agent 循环）

```
用户 → LLM（绑定了多个 Skill 作为 Tool）→ 选择调用 → 执行 → 拿结果 → 继续选或输出
```

- 没有图，没有 Planner/Dispatcher
- 整个流程就是一个 LLM 循环
- LLM 既是决策者又是执行者

```python
# ReAct 模式示例
llm_with_skills = llm.bind_tools([rag_search_skill, web_search_skill, writing_skill])
response = await llm_with_skills.ainvoke(messages)
# LLM 自己决定调哪个 Skill，可能调多次
```

适合：能力少（< 5 个）、流程简单、不需要并行

### 模式 B：Multi-Agent + Skill（本项目的架构）

```
用户 → Planner（看 Skill 摘要，选择）→ Dispatcher（并行分发）→ Skill 执行 → Synthesizer
```

- Planner 根据 Skill 摘要做第一阶段选择
- 被选中的 Skill 在 Worker 中执行（第二阶段加载完整定义）
- 支持并行、Human-in-the-Loop、流式进度

适合：能力多、需要并行、需要审批流、需要精细控制

### 为什么不用 ReAct

| 需求 | ReAct | Multi-Agent + Skill |
|------|-------|-------------------|
| 并行执行多个 Skill | ❌ 串行 | ✅ Send API |
| 审批流（interrupt） | ❌ 不好做 | ✅ 天然支持 |
| 流式进度推送 | ❌ 只有最终输出 | ✅ 每个节点推进度 |
| 流程可控性 | ❌ LLM 全权决定 | ✅ 图编排 |
| 新增 Skill | ✅ 加一个 Tool | ✅ 加一个文件 |

---

## 三、两阶段选择

### 为什么要两阶段

假设有 20 个 Skill，每个 Skill 的完整 prompt 有 500 token：
- 全部塞给 LLM = 10,000 token（浪费 + 干扰决策）
- 两阶段 = 先看 20 条摘要（~400 token）→ 只加载选中的 2-3 个（~1500 token）

### 流程

```
┌─────────────────────────────────────────────────┐
│ 第一阶段：Planner 看摘要，选择 Skill             │
│                                                 │
│ 输入：用户消息 + 所有 Skill 的一句话摘要          │
│ 输出：需要执行的 Skill 名称列表                   │
│                                                 │
│ 例：用户问"Spring Boot 怎么配置数据库"            │
│ Planner 看到：                                   │
│   - rag_search: 平台知识库检索                    │
│   - web_search: 联网搜索实时信息                  │
│   - writing: 文章撰写                            │
│   - chat: 日常对话                                │
│   - translate: 翻译                              │
│   - code_review: 代码审查                         │
│ Planner 选择：["rag_search"]                      │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ 第二阶段：加载完整定义，执行                      │
│                                                 │
│ 加载 rag_search 的：                             │
│   - 完整 SYSTEM_PROMPT（检索策略、输出格式...）    │
│   - 可用 TOOLS（web_search, search_articles...）  │
│   - execute() 函数（查询改写→召回→精排→LLM）      │
│                                                 │
│ 执行并返回结果                                    │
└─────────────────────────────────────────────────┘
```

---

## 四、Skill 文件规范

每个 Skill 是一个独立的 `.py` 文件，放在 `app/skills/` 目录下。
**只要文件里有 `SKILL_META`，就会被自动发现，不需要改任何其他代码。**

### 4.1 Skill 文件结构

```python
# app/skills/xxx_skill.py

# ━━━━━━━━━━━━━ 1. 元信息（必须）━━━━━━━━━━━━━
SKILL_META = {
    "name": "xxx",          # 唯一标识，Planner 用这个名字
    "summary": "一句话描述",  # 第一阶段给 Planner 看的摘要（尽量短）
}

# ━━━━━━━━━━━━━ 2. 完整提示词（必须）━━━━━━━━━━━━━
SYSTEM_PROMPT = """第二阶段加载的完整 prompt..."""

# ━━━━━━━━━━━━━ 3. 依赖的 Tool 名称（可选）━━━━━━━━━━━━━
TOOLS = ["web_search", "search_articles"]  # 引用 TOOL_REGISTRY 中注册的 Tool

# ━━━━━━━━━━━━━ 4. 执行函数（必须）━━━━━━━━━━━━━
async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    """
    Skill 的核心执行逻辑

    :param task_input: Planner 分配的任务描述
    :param history: 会话历史消息
    :param context: 运行时上下文，包含 tools（已解析的 Tool 实例列表）
    :return: {"result": "...", ...} 可以附加 article_cards 等旁路数据
    """
    ...
```

### 4.2 各字段说明

| 字段 | 必须 | 说明 |
|------|------|------|
| `SKILL_META["name"]` | ✅ | 唯一标识，Planner 输出这个名字来选中该 Skill |
| `SKILL_META["summary"]` | ✅ | 一句话描述，第一阶段注入 Planner prompt，**要短** |
| `SYSTEM_PROMPT` | ✅ | 完整提示词，第二阶段加载，可以很长很详细 |
| `TOOLS` | ❌ | 依赖的 Tool 名称列表，为空表示不用工具 |
| `execute()` | ✅ | 异步执行函数，签名固定 |

### 4.3 execute() 的 context 参数

```python
context = {
    "tools": [web_search, search_articles],  # loader 根据 TOOLS 列表自动解析的实例
}
```

Skill 内部通过 `context["tools"]` 拿到 Tool 实例，传给 `run_tool_agent` 使用。
**Skill 不需要自己 import Tool**，由 loader 统一管理。

---

## 五、完整 Skill 示例

### 5.1 RAG 检索 Skill

```python
# app/skills/rag_search.py

SKILL_META = {
    "name": "rag_search",
    "summary": "在平台知识库中检索技术文章、面试题、职场经验，支持语义搜索和关键词搜索",
}

SYSTEM_PROMPT = """你是一个信息检索助手。

已通过平台 RAG 检索到参考资料，见下文。
如果参考资料不足以回答问题（如涉及实时信息、最新动态），请调用 web_search 工具补充联网数据。

【要求】
- 优先使用 RAG 检索到的平台文章回答
- 引用文章时标注来源
- 联网搜索只在 RAG 不足时使用"""

TOOLS = ["web_search", "search_articles", "search_articles_by_knn"]


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.services.query_rewrite import QueryRewriteService
    from app.services.reranker import RerankerService
    from app.clients.es_client import EsVectorStore, EsComponent
    from app.tools.web_search import do_search
    from app.graph.tool_executor import run_tool_agent
    from app.config import settings

    # 1. Query Rewriting
    qr = QueryRewriteService()
    rewrite_result = await qr.rewrite(task_input, history)

    # 2. 多路粗检索
    doc_map = {}
    es_vector = EsVectorStore()
    es_keyword = EsComponent()

    for sq in rewrite_result.get("semantic_queries", []):
        try:
            chunks = await es_vector.search(sq, settings.COARSE_TOP_K, settings.COARSE_SIMILARITY_THRESHOLD)
            for c in chunks:
                key = f"{c['article_id']}_{c['chunk_index']}"
                doc_map.setdefault(key, c)
        except Exception:
            pass

    for kw in rewrite_result.get("keywords", []):
        try:
            articles = await es_keyword.search(kw, page_size=5)
            for a in articles:
                key = f"keyword_{a['article_id']}"
                doc_map.setdefault(key, {
                    "article_id": a["article_id"], "title": a["title"],
                    "content": a.get("summary", ""), "chunk_index": 0,
                })
        except Exception:
            pass

    # 联网兜底
    if not doc_map:
        queries = rewrite_result.get("semantic_queries") or rewrite_result.get("keywords", [])
        if queries:
            try:
                web_results = await do_search(queries[0], size=5)
                for i, item in enumerate(web_results):
                    doc_map[f"web_{i}"] = {
                        "article_id": f"web_{i}", "title": item.get("title", ""),
                        "content": item.get("content", ""), "chunk_index": i, "score": 0.1,
                    }
            except Exception:
                pass

    candidates = list(doc_map.values())

    # 3. Reranker 精排
    reranker = RerankerService()
    ranked = reranker.rerank(task_input, candidates) if candidates else []

    # 4. 旁路卡片
    article_cards = []
    for r in ranked:
        aid = str(r.get("article_id", ""))
        if aid and not aid.startswith("web_"):
            article_cards.append({
                "articleId": aid,
                "title": r.get("title", ""),
                "coverImage": r.get("cover", ""),
                "authorName": r.get("author_name", ""),
                "viewCount": r.get("view_count", 0),
                "likeCount": r.get("like_count", 0),
            })

    # 5. 构建 RAG 上下文
    if not ranked:
        rag_context = "未找到相关资料"
    else:
        parts = []
        for i, doc in enumerate(ranked[:5]):
            title = doc.get("title", "无标题")
            content = doc.get("content", "")[:500]
            parts.append(f"【{i + 1}. {title}】\n{content}")
        rag_context = "\n\n".join(parts)

    # 6. LLM + Tool 联网补充
    from datetime import datetime
    reply = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT + f"\n【当前日期】{datetime.now().strftime('%Y-%m-%d')}",
        user_input=f"任务：{task_input}\n\nRAG 参考资料：\n{rag_context}",
        tools=context["tools"],
        max_rounds=2,
    )

    return {"result": reply, "article_cards": article_cards}
```

### 5.2 联网搜索 Skill

```python
# app/skills/web_search_skill.py

SKILL_META = {
    "name": "web_search_skill",
    "summary": "联网搜索实时信息、最新资讯，适合时效性强或平台文章里找不到的问题",
}

SYSTEM_PROMPT = """你是联网搜索助手。
根据搜索结果整理回复，注明信息来源。
如果搜索结果不相关，诚实告知。"""

TOOLS = ["web_search"]


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.graph.tool_executor import run_tool_agent

    reply = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT,
        user_input=task_input,
        tools=context["tools"],
        max_rounds=2,
    )
    return {"result": reply}
```

### 5.3 日常对话 Skill

```python
# app/skills/chat.py

SKILL_META = {
    "name": "chat",
    "summary": "日常对话、闲聊、简单技术问答，不需要搜索",
}

SYSTEM_PROMPT = """你是一个智能博客平台助手，负责日常对话和技术问答。
保持回复简洁有条理，如果不确定，诚实告知。"""

TOOLS = []


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.graph.tool_executor import run_tool_agent

    reply = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT,
        user_input=task_input,
        tools=[],
    )
    return {"result": reply}
```

### 5.4 写作 Skill（带 Human-in-the-Loop）

```python
# app/skills/writing.py

SKILL_META = {
    "name": "writing",
    "summary": "撰写技术文章、博客、教程，生成草稿后需要用户确认",
}

SYSTEM_PROMPT = """你是一个专业的技术写作助手。
输出完整的文章草稿（Markdown 格式），包含标题、正文、代码示例。
不要输出过渡性文字，直接输出草稿。"""

TOOLS = ["web_search", "search_articles", "search_articles_by_knn"]

# 标记该 Skill 支持 interrupt
SUPPORTS_INTERRUPT = True


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from langgraph.types import interrupt
    from app.graph.tool_executor import run_tool_agent

    # 1. 生成草稿
    draft = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT,
        user_input=task_input,
        tools=context["tools"],
        max_rounds=2,
    )

    # 2. interrupt 等用户确认
    user_decision = interrupt({
        "action": "confirm_publish",
        "draft": draft,
        "message": "草稿已生成，是否发布？",
    })

    # 3. 处理用户决策
    if user_decision == "approve":
        return {"result": draft}
    elif user_decision == "reject":
        return {"result": "用户取消了发布"}
    else:
        revised = await run_tool_agent(
            system_prompt=SYSTEM_PROMPT,
            user_input=f"原草稿：\n{draft}\n\n用户修改意见：{user_decision}\n\n请重新生成。",
            tools=context["tools"],
            max_rounds=2,
        )
        return {"result": revised}
```

### 5.5 数据分析 Skill

```python
# app/skills/analysis.py

SKILL_META = {
    "name": "analysis",
    "summary": "数据分析、趋势对比、技术选型分析，可搜索资料辅助分析",
}

SYSTEM_PROMPT = """你是一个数据分析专家。
使用数据和事实支撑观点，提供对比表格或列表，给出可操作的建议。"""

TOOLS = ["web_search", "search_articles", "search_articles_by_knn"]


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.graph.tool_executor import run_tool_agent

    reply = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT,
        user_input=task_input,
        tools=context["tools"],
        max_rounds=2,
    )
    return {"result": reply}
```

---

## 六、Skill Loader（自动发现引擎）

```python
# app/skills/loader.py

import importlib
import pkgutil
from pathlib import Path

from app.tools.web_search import web_search
from app.tools.article_tool import search_articles, search_articles_by_knn

# Tool 注册表：Skill 文件里的 TOOLS 列表引用的是这里的名字
TOOL_REGISTRY = {
    "web_search": web_search,
    "search_articles": search_articles,
    "search_articles_by_knn": search_articles_by_knn,
}


class SkillLoader:
    """
    Skill 自动发现与管理

    启动时扫描 app/skills/ 目录，自动加载所有含 SKILL_META 的 .py 文件。
    新增 Skill 只需在目录下放一个文件，不需要改这里的代码。
    """

    def __init__(self):
        self._skills: dict[str, dict] = {}

    def discover(self):
        """扫描 app/skills/ 目录，加载所有 Skill 模块"""
        skills_dir = Path(__file__).parent
        for finder, name, _ in pkgutil.iter_modules([str(skills_dir)]):
            if name in ("loader", "__init__"):
                continue
            try:
                module = importlib.import_module(f"app.skills.{name}")
                if hasattr(module, "SKILL_META") and hasattr(module, "execute"):
                    meta = module.SKILL_META
                    tool_names = getattr(module, "TOOLS", [])
                    self._skills[meta["name"]] = {
                        "meta": meta,
                        "module": module,
                        "tools": [TOOL_REGISTRY[t] for t in tool_names if t in TOOL_REGISTRY],
                        "supports_interrupt": getattr(module, "SUPPORTS_INTERRUPT", False),
                    }
            except Exception as e:
                print(f"加载 Skill {name} 失败: {e}")

    def get_summaries(self) -> str:
        """
        生成所有 Skill 的摘要，注入 Planner prompt

        输出格式：
        - rag_search: 在平台知识库中检索技术文章...
        - chat: 日常对话...
        """
        lines = []
        for skill in self._skills.values():
            m = skill["meta"]
            lines.append(f"- {m['name']}: {m['summary']}")
        return "\n".join(lines)

    def get_skill(self, name: str) -> dict | None:
        """按名字查找 Skill"""
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        """返回所有已注册的 Skill 名"""
        return list(self._skills.keys())

    async def run_skill(self, name: str, task_input: str, history: list[dict]) -> dict:
        """
        执行指定 Skill

        :param name: Skill 名称（SKILL_META["name"]）
        :param task_input: 任务描述
        :param history: 会话历史
        :return: Skill 返回的 dict（至少包含 "result" 字段）
        """
        skill = self._skills.get(name)
        if not skill:
            return {"result": f"技能 '{name}' 不存在，可用技能: {', '.join(self.list_names())}"}

        context = {"tools": skill["tools"]}
        return await skill["module"].execute(task_input, history, context)


# 全局单例
skill_loader = SkillLoader()
skill_loader.discover()
```

---

## 七、接入 LangGraph 图

### 7.1 通用 Skill Worker 节点

```python
# app/graph/nodes/skill_worker.py

from app.graph.state import AgentState
from app.skills.loader import skill_loader


async def skill_worker_node(state: AgentState) -> dict:
    """
    通用 Skill 执行节点

    从 state["_skill_name"] 读取要执行的 Skill 名称，
    调用 skill_loader.run_skill() 执行。

    一个节点替代所有 xxx_worker_node。
    """
    if state.get("cancelled"):
        return {"worker_results": []}

    skill_name = state.get("_skill_name", "chat")
    task_input = state["task_descriptions"].get(skill_name, state["user_message"])
    history = state.get("history_messages", [])

    result = await skill_loader.run_skill(skill_name, task_input, history)

    output = {
        "worker_results": [{
            "worker_name": skill_name,
            "result": result.get("result", ""),
        }]
    }

    # 旁路数据（如文章卡片）
    if result.get("article_cards"):
        output["article_cards"] = result["article_cards"]

    return output
```

### 7.2 Dispatcher 改造

```python
# app/graph/nodes/dispatcher.py

from langgraph.types import Send
from app.graph.state import AgentState


def dispatcher_node(state: AgentState) -> list[Send]:
    """Planner 选了哪些 Skill，就 Send 到 skill_worker 执行"""
    sends = []
    for skill_name in state["active_workers"]:
        sends.append(Send("skill_worker", {**state, "_skill_name": skill_name}))

    if not sends:
        sends.append(Send("skill_worker", {**state, "_skill_name": "chat"}))

    return sends
```

### 7.3 Builder 改造

```python
# app/graph/builder.py

def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("skill_worker", skill_worker_node)  # 1 个通用节点
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatcher_node)
    graph.add_edge("skill_worker", "synthesizer")  # 1 条边
    graph.add_edge("synthesizer", END)

    return graph
```

### 7.4 Planner 改造

```python
# app/graph/nodes/planner.py

from app.skills.loader import skill_loader

PLANNER_SYSTEM_PROMPT = f"""你是一个智能任务规划器。

【可用的技能】
{skill_loader.get_summaries()}

请根据用户消息选择需要的技能。
简单问候/闲聊 → 只用 chat
复杂任务可以组合多个技能。

请以 JSON 格式返回：
{{"active_workers": ["skill1", "skill2"], "task_descriptions": {{"skill1": "...", "skill2": "..."}}}}
"""
```

---

## 八、新增 Skill 全流程

**示例：新增一个「翻译」Skill**

### 只需做一件事：创建文件

```python
# app/skills/translate.py    ← 放进去就完了

SKILL_META = {
    "name": "translate",
    "summary": "中英文互译、技术文档翻译，保持术语准确",
}

SYSTEM_PROMPT = """你是专业的技术翻译助手。
将用户提供的内容翻译为目标语言。
- 技术术语优先使用业界通用翻译
- 不确定的术语用 web_search 查询标准翻译
- 保持原文的格式和结构"""

TOOLS = ["web_search"]


async def execute(task_input: str, history: list[dict], context: dict) -> dict:
    from app.graph.tool_executor import run_tool_agent

    reply = await run_tool_agent(
        system_prompt=SYSTEM_PROMPT,
        user_input=task_input,
        tools=context["tools"],
        max_rounds=1,
    )
    return {"result": reply}
```

**不需要改任何其他文件。** 下次启动时：
1. `skill_loader.discover()` 自动扫描到 `translate.py`
2. Planner prompt 自动包含 `- translate: 中英文互译...`
3. 用户说「帮我翻译这段代码注释」→ Planner 选中 `translate` → 自动执行

---

## 九、对比总结

| 维度 | 硬编码 Worker（改造前） | Skill 自发现（最终形态） |
|------|----------------------|----------------------|
| 新增能力 | 改 4-5 个文件 | **只加 1 个文件** |
| Planner prompt | 手动维护 Worker 列表 | 自动生成 |
| Dispatcher | if/elif 硬编码 | 通用 Send + skill_name |
| Graph 节点 | N 个 Worker 节点 + N 条边 | 1 个 skill_worker + 1 条边 |
| Tool 调用循环 | 每个 Worker 重复写 | `run_tool_agent` 只写 1 次 |
| 删除能力 | 改 4-5 个文件 | **删 1 个文件** |
| 单元测试 | 需要启动图 | `await skill_loader.run_skill("xxx", ...)` |

---

## 十、目录结构

```
app/skills/
├── __init__.py
├── loader.py              # 自动发现引擎（不需要改）
├── rag_search.py          # RAG 两阶段检索
├── web_search_skill.py    # 联网搜索
├── chat.py                # 日常对话
├── writing.py             # 文章写作 + interrupt
├── analysis.py            # 数据分析
└── translate.py           # ← 新加的，不改其他文件
```
