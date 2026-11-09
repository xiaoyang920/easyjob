# Tool 重构指南：从确定性调用到 LangChain @tool 模式

---

## 0. tool 放在哪里 + 一个文件多个 tool

### tool 不应该放在 node 文件里

❌ 错误的写法（tool 和 node 耦合在一起）：

```
graph/nodes/search_worker.py
  ├── @tool web_search(...)       ← 不该放这里
  └── def search_worker_node(...) ← node 逻辑
```

问题：`writing_worker` 也需要 `web_search`，就得重复定义或跨文件乱引用。

### ✅ 正确：tool 定义放在 `tools/` 目录

```
tools/
  ├── web_search.py       ← WebSearchTool 类 + @tool 函数
  └── article_tool.py     ← ArticleTool 类 + @tool 函数

graph/nodes/
  ├── search_worker.py    ← 只 import tool，不定义
  └── writing_worker.py   ← 同样 import 复用
```

### 一个文件里可以定义多个 @tool，没有限制

```python
# tools/web_search.py

from langchain_core.tools import tool

class WebSearchTool:
    ...  # 原有类代码不动

# 模块级实例（只初始化一次）
_instance = WebSearchTool()

# ✅ 一个文件可以定义多个 @tool
@tool
def web_search(query: str) -> str:
    """
    联网搜索实时信息。
    适合：最新资讯、时效性强的问题、平台内找不到的内容。
    不适合：可以从已有参考资料回答的问题。
    """
    results = _instance.search(query, size=5)
    if not results:
        return "未找到相关网页信息"
    return "\n".join([f"- [{r['title']}] {r['content']}" for r in results[:3]])


@tool
def web_search_news(query: str) -> str:
    """
    专门搜索最新新闻资讯。
    适合：今日热点、行业动态、最新政策。
    """
    results = _instance.search(query, size=3)
    # 过滤出新闻类结果
    news = [r for r in results if "新闻" in r.get("title", "") or "资讯" in r.get("title", "")]
    return "\n".join([f"- {r['title']}: {r['content'][:100]}" for r in news]) or "未找到相关新闻"
```

```python
# tools/article_tool.py

from langchain_core.tools import tool

class ArticleTool:
    ...  # 原有类代码不动

_instance = ArticleTool()

@tool
def search_platform_articles(query: str) -> str:
    """
    搜索平台内的技术文章、职场经验、面试题等内容。
    适合：查找平台已有的知识内容。
    """
    results = _instance.search_articles(query, top_k=3)
    if not results:
        return "平台内未找到相关文章"
    return "\n".join([f"- [{r['title']}] {r.get('summary', '')[:150]}" for r in results])


@tool
def search_reference(query: str) -> str:
    """
    搜索写作参考资料（平台文章 + 向量检索）。
    适合：writing worker 需要知识点支撑时使用。
    """
    results = _instance.search_articles(query, top_k=5)
    if not results:
        return "未找到相关参考资料"
    return "\n".join([f"- [{r['title']}] {r.get('summary', '')[:200]}" for r in results])
```

### node 里只做 import + 组合

```python
# graph/nodes/search_worker.py
from app.tools.web_search import web_search          # 直接用
from app.tools.article_tool import search_platform_articles

llm_with_tools = llm.bind_tools([web_search, search_platform_articles])

# graph/nodes/writing_worker.py
from app.tools.web_search import web_search          # 同一个 tool，直接复用
from app.tools.article_tool import search_reference  # 写作专用的 tool

llm_with_tools = llm.bind_tools([search_reference, web_search])
```

这样 tool 的实现只写一次，多个 node 按需 import 组合。

---

## 1. 现在的问题

### 当前 `search_worker.py` 联网搜索逻辑

```python
# 现在的写法：代码硬判断"结果为空才联网"
if not doc_map:
    web_results = web_search_tool.search(fallback_query, size=5)
```

**问题**：
- 只有 ES 完全没结果才联网，但很多问题 ES 有一点结果但不够用（比如问今天的新闻）
- LLM 无法根据问题性质判断"这个问题需要实时数据"
- 联网搜索变成了兜底，而不是按需补充

### 当前 `writing` / `analysis` Worker

```python
# graph/nodes/writing_worker.py（占位节点，未实现）
def writing_worker_node(state: AgentState) -> dict:
    return {"worker_results": [{"worker_name": "writing", "result": "writing TODO"}]}
```

**问题**：
- `writing` 生成文章时需要参考资料，但现在没有搜索能力
- 完全依赖用户输入和 LLM 本身的知识，质量差

---

## 2. 目标架构

```
search_worker:
  QueryRewrite → 向量检索 + 关键词检索 → Reranker   ← 确定性，每次必跑
                                         ↓
                              LLM 判断是否需要联网   ← @tool，LLM 决定
                                         ↓
                                    LLM 生成回复

writing_worker:
  LLM 判断是否需要搜索参考资料  ← @tool，LLM 决定
              ↓
         LLM 生成文章
```

---

## 3. LangChain @tool 的用法

### 3.1 基本写法

```python
from langchain_core.tools import tool

@tool
def web_search(query: str) -> str:
    """
    联网搜索实时信息。
    适合：最新新闻、实时数据、平台文章里没有的内容、时效性强的问题。
    不适合：可以从已有资料回答的问题。
    """
    results = web_search_tool.search(query, size=5)
    if not results:
        return "未找到相关网页信息"
    lines = [f"- [{r['title']}] {r['content']}" for r in results[:3]]
    return "\n".join(lines)
```

**重点**：docstring 非常重要，LLM 靠它理解"什么时候该调这个工具"。

### 3.2 绑定给 LLM

```python
llm = ChatOpenAI(model="deepseek-chat", ...)
llm_with_tools = llm.bind_tools([web_search])
```

### 3.3 处理工具调用结果

LLM 不一定会调工具，需要判断：

```python
from langchain_core.messages import ToolMessage

response = llm_with_tools.invoke(messages)

# 判断 LLM 是否决定调工具
if response.tool_calls:
    # LLM 决定调工具
    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        # 执行工具
        if tool_name == "web_search":
            tool_result = web_search.invoke(tool_args)
        
        # 把工具结果追加到消息列表，让 LLM 继续生成
        messages.append(response)  # AI 的工具调用消息
        messages.append(ToolMessage(
            content=tool_result,
            tool_call_id=tool_call["id"]
        ))
    
    # 再次调用 LLM，让它基于工具结果生成最终回复
    final_response = llm_with_tools.invoke(messages)
    result = final_response.content

else:
    # LLM 直接回答，不需要工具
    result = response.content
```

---

## 4. search_worker 改造方案

### 改造前（现在）

```python
def search_worker_node(state):
    # 1. QueryRewrite
    # 2. 粗检索（向量 + 关键词）
    # 3. Reranker
    # 4. 构建 RAG 上下文
    # 5. LLM 生成（无工具，联网只在结果为空时兜底）
```

### 改造后

```python
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage

# 注册联网搜索为 tool
@tool
def web_search(query: str) -> str:
    """
    联网搜索实时信息。
    适合：最新资讯、时效性强的问题、平台内找不到的内容。
    """
    results = web_search_tool_instance.search(query, size=5)
    if not results:
        return "未找到相关网页信息"
    return "\n".join([f"- [{r['title']}] {r['content']}" for r in results[:3]])


SEARCH_SYSTEM_PROMPT = """你是信息检索助手。

【RAG 参考资料】已通过平台文章检索获得，见下文。

如果参考资料不足以回答问题（比如问题涉及实时信息、最新动态），
请调用 web_search 工具补充联网数据。

【当前日期】{current_date}
"""


def search_worker_node(state: AgentState) -> dict:
    task_input = state["task_descriptions"].get("search", state["user_message"])
    history_messages = state["history_messages"]

    # 1-4. 确定性流程不变（QueryRewrite + 粗检索 + Reranker + 构建上下文）
    rewrite_result = query_rewrite_service.rewrite(task_input, history_messages)
    candidates = execute_coarse_retrieval_without_web(rewrite_result)  # 去掉原来的联网兜底
    ranked = reranker_service.rerank(task_input, candidates) if candidates else []
    rag_context = build_rag_context(ranked)

    # 5. LLM + tool 决定是否联网
    llm = ChatOpenAI(model="deepseek-chat", ...)
    llm_with_tools = llm.bind_tools([web_search])

    messages = [
        SystemMessage(content=SEARCH_SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        )),
        HumanMessage(content=f"任务：{task_input}\n\n平台参考资料：\n{rag_context}"),
    ]

    response = llm_with_tools.invoke(messages)

    # 处理工具调用
    if response.tool_calls:
        messages.append(response)
        for tool_call in response.tool_calls:
            tool_result = web_search.invoke(tool_call["args"])
            messages.append(ToolMessage(
                content=tool_result,
                tool_call_id=tool_call["id"]
            ))
        final_response = llm_with_tools.invoke(messages)
        result = final_response.content
    else:
        result = response.content

    return {"worker_results": [{"worker_name": "search", "result": result}]}
```

**关键变化**：
- `execute_coarse_retrieval` 里去掉原来的联网兜底逻辑
- 联网搜索变成 `@tool`，LLM 自己判断要不要调

---

## 5. writing_worker 实现方案

```python
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage

@tool
def search_reference(query: str) -> str:
    """
    搜索写作参考资料。
    当需要特定知识点、数据、案例来支撑文章内容时使用。
    """
    # 向量检索 + 关键词检索
    chunks = es_vector_store.search(query, top_k=3, threshold=0.4)
    articles = article_tool.search_articles(query, top_k=3)
    
    results = []
    for chunk in chunks[:2]:
        results.append(f"- [{chunk['title']}] {chunk['content'][:200]}")
    for article in articles[:2]:
        results.append(f"- [{article['title']}] {article.get('summary', '')[:200]}")
    
    return "\n".join(results) if results else "未找到相关参考资料"


WRITING_SYSTEM_PROMPT = """你是专业写作助手，负责撰写高质量文章和内容。

【写作原则】
- 结构清晰，有标题和段落
- 内容具体，有数据和案例支撑
- 语言流畅自然
- 如需特定知识点，可调用 search_reference 工具搜索参考资料

【当前日期】{current_date}
"""


def writing_worker_node(state: AgentState) -> dict:
    task_input = state["task_descriptions"].get("writing", state["user_message"])
    
    # search worker 的结果可以作为额外上下文
    search_results = ""
    for wr in state.get("worker_results", []):
        if wr.get("worker_name") == "search":
            search_results = wr.get("result", "")

    llm = ChatOpenAI(model="deepseek-chat", ...)
    llm_with_tools = llm.bind_tools([search_reference])

    messages = [
        SystemMessage(content=WRITING_SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        )),
        HumanMessage(content=(
            f"写作任务：{task_input}"
            + (f"\n\n已有参考资料：\n{search_results}" if search_results else "")
        )),
    ]

    # 最多允许 2 轮工具调用（搜索 → 生成）
    for _ in range(2):
        response = llm_with_tools.invoke(messages)
        
        if not response.tool_calls:
            break
        
        messages.append(response)
        for tool_call in response.tool_calls:
            tool_result = search_reference.invoke(tool_call["args"])
            messages.append(ToolMessage(
                content=tool_result,
                tool_call_id=tool_call["id"]
            ))

    return {"worker_results": [{"worker_name": "writing", "result": response.content}]}
```

---

## 6. analysis_worker 实现方案

`analysis` 主要靠 LLM 推理，不需要 tool，直接用已有数据：

```python
ANALYSIS_SYSTEM_PROMPT = """你是数据分析专家，负责对信息进行深度分析。

【分析原则】
- 找出规律、趋势、对比点
- 给出有依据的结论
- 使用结构化输出（对比表格、要点列表等）
- 语言客观，避免主观臆断

【当前日期】{current_date}
"""


def analysis_worker_node(state: AgentState) -> dict:
    task_input = state["task_descriptions"].get("analysis", state["user_message"])
    
    # 利用 search worker 已经搜到的结果
    search_results = ""
    for wr in state.get("worker_results", []):
        if wr.get("worker_name") == "search":
            search_results = wr.get("result", "")

    llm = ChatOpenAI(model="deepseek-chat", ...)

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        )),
        HumanMessage(content=(
            f"分析任务：{task_input}"
            + (f"\n\n数据来源：\n{search_results}" if search_results else "")
        )),
    ]

    response = llm.invoke(messages)
    return {"worker_results": [{"worker_name": "analysis", "result": response.content}]}
```

---

## 7. 涉及的文件改动清单

| 文件 | 改动内容 |
|---|---|
| `app/graph/nodes/search_worker.py` | 去掉联网兜底逻辑，改为 `@tool` + `bind_tools` |
| `app/graph/nodes/writing_worker.py` | 新建，实现 `@tool` 搜索参考资料 + LLM 生成 |
| `app/graph/nodes/analysis_worker.py` | 新建，纯 LLM 分析，无 tool |
| `app/graph/builder.py` | 注册 `writing_worker_node` 和 `analysis_worker_node` |

---

## 8. 注意事项

### ToolMessage 必须紧跟在 AI 工具调用消息后面

```python
# 顺序必须是：
# 1. HumanMessage（用户输入）
# 2. AIMessage（含 tool_calls，LLM 决定调工具）
# 3. ToolMessage（工具执行结果，tool_call_id 要对应）
# 4. AIMessage（LLM 基于工具结果生成最终回复）
messages.append(response)           # step 2
messages.append(ToolMessage(...))   # step 3
final = llm.invoke(messages)        # step 4
```

### tool 的 docstring 要写清楚"什么时候用"

LLM 完全靠 docstring 决定要不要调工具：

```python
# ❌ 太简单，LLM 不知道什么时候用
@tool
def web_search(query: str) -> str:
    """搜索网页"""

# ✅ 清楚描述适用场景
@tool  
def web_search(query: str) -> str:
    """
    联网搜索实时信息。
    适合：最新资讯、时效性强的问题、平台内找不到的内容。
    不适合：可以从已有参考资料回答的问题。
    """
```

### 工具调用轮次要有上限

避免 LLM 死循环调工具：

```python
for _ in range(2):   # 最多 2 轮
    response = llm_with_tools.invoke(messages)
    if not response.tool_calls:
        break
    # 处理工具调用...
```
