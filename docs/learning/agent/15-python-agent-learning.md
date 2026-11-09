# Python Agent 学习指南

本文档帮助你从 Java Spring AI 过渡到 Python LangChain/LangGraph，实现 Agent 模块的 Python 化。

---

## 1. Python 基础速成

### 1.1 与 Java 的对比

| Java | Python |
|------|--------|
| `public class Foo {}` | `class Foo:` |
| `private String name;` | `self.name = ""` |
| `public void method() {}` | `def method(self):` |
| `List<String> list = new ArrayList<>();` | `list = []` |
| `Map<String, Object> map = new HashMap<>();` | `dict = {}` |
| `for (String s : list) {}` | `for s in list:` |
| `if (x == null) {}` | `if x is None:` |
| `@Autowired` | 无，直接传参或用依赖注入框架 |

### 1.2 常用语法

```python
# 变量（无需声明类型）
name = "hello"
count = 10
items = ["a", "b", "c"]
config = {"key": "value", "port": 8080}

# 函数
def greet(name: str) -> str:
    return f"Hello, {name}"

# 类
class UserService:
    def __init__(self, db_client):
        self.db = db_client
    
    def get_user(self, user_id: int) -> dict:
        return self.db.find(user_id)

# 列表推导式（类似 Java Stream）
numbers = [1, 2, 3, 4, 5]
squares = [n * n for n in numbers]  # [1, 4, 9, 16, 25]
evens = [n for n in numbers if n % 2 == 0]  # [2, 4]

# 字典操作
user = {"name": "Tom", "age": 20}
name = user.get("name", "default")  # 类似 getOrDefault
user["email"] = "tom@example.com"   # 添加/更新

# 异步（类似 CompletableFuture）
import asyncio

async def fetch_data():
    await asyncio.sleep(1)
    return "data"

async def main():
    result = await fetch_data()
    print(result)
```

### 1.3 类型注解（推荐使用）

```python
from typing import List, Dict, Optional

def process(
    items: List[str],
    config: Dict[str, any],
    limit: Optional[int] = None
) -> List[str]:
    return items[:limit]
```

---

## 2. FastAPI 基础

FastAPI 是 Python 的高性能 Web 框架，类似 Spring Boot。

### 2.1 安装

```bash
pip install fastapi uvicorn
```

### 2.2 基本示例

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# 请求体模型（类似 Java DTO）
class ChatRequest(BaseModel):
    user_id: int
    message: str
    conversation_id: Optional[int] = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int

# GET 请求
@app.get("/health")
def health_check():
    return {"status": "ok"}

# POST 请求
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # 处理逻辑
    return ChatResponse(reply="Hello!", conversation_id=123)

# 启动：uvicorn main:app --reload
```

### 2.3 SSE 流式输出

```python
from fastapi.responses import StreamingResponse
import asyncio

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def generate():
        for char in "Hello, this is streaming response":
            yield f"data: {char}\n\n"
            await asyncio.sleep(0.05)
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 2.4 对比 Spring Boot

| Spring Boot | FastAPI |
|-------------|---------|
| `@RestController` | `app = FastAPI()` |
| `@GetMapping("/path")` | `@app.get("/path")` |
| `@PostMapping("/path")` | `@app.post("/path")` |
| `@RequestBody` | 函数参数 + Pydantic 模型 |
| `@PathVariable` | `def get(id: int)` |
| `@RequestParam` | `def get(name: str = Query(...))` |
| `ResponseEntity<T>` | 直接返回对象或 `Response` |

---

## 3. LangChain 基础

LangChain 是 LLM 应用开发框架，提供 Prompt、Chain、Tool 等抽象。

### 3.1 安装

```bash
pip install langchain langchain-openai langchain-community
```

### 3.2 基本概念

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. 创建 LLM（类似 ChatModel）
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key="your-api-key",
    base_url="https://api.deepseek.com/v1"
)

# 2. 创建 Prompt 模板
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个智能助手"),
    ("human", "{input}")
])

# 3. 创建 Chain（类似 Pipeline）
chain = prompt | llm | StrOutputParser()

# 4. 调用
result = chain.invoke({"input": "你好"})
print(result)
```

### 3.3 结构化输出（类似 Spring AI entity()）

```python
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser

# 定义输出结构
class RewriteResult(BaseModel):
    semantic_queries: list[str] = Field(description="语义扩展查询列表")
    keywords: list[str] = Field(description="关键词列表")

# 创建解析器
parser = PydanticOutputParser(pydantic_object=RewriteResult)

# 在 Prompt 中加入格式说明
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是查询改写助手。\n{format_instructions}"),
    ("human", "{query}")
])

chain = prompt | llm | parser

result: RewriteResult = chain.invoke({
    "query": "Redis怎么用",
    "format_instructions": parser.get_format_instructions()
})
print(result.semantic_queries)
print(result.keywords)
```

### 3.4 Tool Calling

```python
from langchain_core.tools import tool

@tool
def search_articles(query: str) -> str:
    """搜索平台文章"""
    # 调用 ES 搜索
    return f"找到关于 {query} 的文章..."

@tool
def web_search(query: str) -> str:
    """联网搜索"""
    return f"网络搜索结果: {query}"

# 绑定工具到 LLM
llm_with_tools = llm.bind_tools([search_articles, web_search])

# 调用
response = llm_with_tools.invoke("搜索 Redis 相关文章")
```

---

## 4. LangGraph 基础

LangGraph 是基于 LangChain 的图编排框架，用于构建 Multi-Agent 系统。

### 4.1 安装

```bash
pip install langgraph
```

### 4.2 核心概念对比

| 你的 Java 实现 | LangGraph |
|---------------|-----------|
| `OverAllState` | `TypedDict` 状态类 |
| `NodeAction` | 普通函数 |
| `StateGraph.addNode()` | `graph.add_node()` |
| `StateGraph.addEdge()` | `graph.add_edge()` |
| `CompletableFuture` 并行 | `Send` API 或并行分支 |
| `START` / `END` | `START` / `END` |

### 4.3 基本示例

```python
from typing import TypedDict, List, Annotated
from langgraph.graph import StateGraph, START, END
from operator import add

# 1. 定义状态（类似 OverAllState）
class AgentState(TypedDict):
    user_message: str
    history_messages: List[dict]
    active_workers: List[str]
    worker_results: Annotated[List[dict], add]  # 可累加
    final_reply: str

# 2. 定义节点函数（类似 NodeAction）
def planner_node(state: AgentState) -> dict:
    """规划节点：分析意图，决定调用哪些 Worker"""
    user_message = state["user_message"]
    # 调用 LLM 分析...
    return {
        "active_workers": ["search", "chat"]
    }

def search_worker(state: AgentState) -> dict:
    """搜索 Worker"""
    # 执行搜索逻辑...
    return {
        "worker_results": [{"worker": "search", "result": "搜索结果..."}]
    }

def chat_worker(state: AgentState) -> dict:
    """聊天 Worker"""
    return {
        "worker_results": [{"worker": "chat", "result": "聊天回复..."}]
    }

def synthesizer_node(state: AgentState) -> dict:
    """汇总节点"""
    results = state["worker_results"]
    # 汇总逻辑...
    return {"final_reply": "最终回复"}

# 3. 构建图
graph = StateGraph(AgentState)

# 添加节点
graph.add_node("planner", planner_node)
graph.add_node("search", search_worker)
graph.add_node("chat", chat_worker)
graph.add_node("synthesizer", synthesizer_node)

# 添加边
graph.add_edge(START, "planner")
graph.add_edge("planner", "search")
graph.add_edge("planner", "chat")
graph.add_edge("search", "synthesizer")
graph.add_edge("chat", "synthesizer")
graph.add_edge("synthesizer", END)

# 4. 编译并运行
app = graph.compile()
result = app.invoke({
    "user_message": "帮我搜索 Redis 教程",
    "history_messages": [],
    "active_workers": [],
    "worker_results": [],
    "final_reply": ""
})
print(result["final_reply"])
```

### 4.4 条件路由（类似你的 Dispatcher 逻辑）

```python
from langgraph.graph import StateGraph, START, END

def route_workers(state: AgentState) -> list[str]:
    """根据 active_workers 决定下一步"""
    return state["active_workers"]

graph = StateGraph(AgentState)
graph.add_node("planner", planner_node)
graph.add_node("search", search_worker)
graph.add_node("chat", chat_worker)
graph.add_node("synthesizer", synthesizer_node)

# 条件路由
graph.add_conditional_edges(
    "planner",
    route_workers,
    {
        "search": "search",
        "chat": "chat"
    }
)
```

### 4.5 并行执行

```python
from langgraph.constants import Send

def dispatcher(state: AgentState):
    """并行分发到多个 Worker"""
    workers = state["active_workers"]
    # 返回 Send 列表，LangGraph 会并行执行
    return [Send(worker, state) for worker in workers]

graph.add_conditional_edges("planner", dispatcher)
```

---

## 5. 项目迁移对照表

### 5.1 Java → Python 组件对应

| Java 组件 | Python 实现 |
|-----------|-------------|
| `AgentService` | FastAPI 路由 + LangGraph |
| `PlannerNode` | LangGraph node 函数 |
| `DispatcherNode` | `add_conditional_edges` + `Send` |
| `SearchWorkerNode` | LangGraph node + ES 客户端 |
| `ChatWorkerNode` | LangGraph node |
| `SynthesizerNode` | LangGraph node |
| `QueryRewriteService` | LangChain Chain + Pydantic |
| `RerankerService` | HTTP 调用 DashScope API |
| `EsVectorStore` | elasticsearch-py |
| `RedisComponent` | redis-py |

### 5.2 目录结构建议

```
python-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py         # AgentState 定义
│   │   ├── nodes/
│   │   │   ├── planner.py
│   │   │   ├── dispatcher.py
│   │   │   ├── search_worker.py
│   │   │   ├── chat_worker.py
│   │   │   └── synthesizer.py
│   │   └── builder.py       # 图构建
│   ├── services/
│   │   ├── query_rewrite.py
│   │   ├── reranker.py
│   │   └── embedding.py
│   ├── tools/
│   │   ├── article_tool.py
│   │   └── web_search.py
│   └── clients/
│       ├── es_client.py
│       └── redis_client.py
├── requirements.txt
└── README.md
```

### 5.3 requirements.txt

```
fastapi==0.109.0
uvicorn==0.27.0
langchain==0.1.0
langchain-openai==0.0.5
langgraph==0.0.20
elasticsearch==8.12.0
redis==5.0.1
httpx==0.26.0
pydantic==2.5.3
python-dotenv==1.0.0
```

---

## 6. 学习路线

1. **第一周：Python 基础**
   - 语法、类型注解、异步编程
   - 推荐：[Python 官方教程](https://docs.python.org/zh-cn/3/tutorial/)

2. **第二周：FastAPI**
   - 路由、请求/响应、依赖注入
   - 推荐：[FastAPI 官方文档](https://fastapi.tiangolo.com/zh/)

3. **第三周：LangChain**
   - Prompt、Chain、Tool、结构化输出
   - 推荐：[LangChain 官方文档](https://python.langchain.com/docs/)

4. **第四周：LangGraph**
   - StateGraph、Node、Edge、条件路由
   - 推荐：[LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)

5. **第五周：项目迁移**
   - 搭建 FastAPI 服务
   - 逐个迁移 Node 逻辑
   - 对接 ES、Redis

---

## 7. 常见问题

### Q1: Python 虚拟环境怎么用？

```bash
# 创建虚拟环境
python -m venv venv

# 激活（Windows）
.\venv\Scripts\activate

# 激活（Mac/Linux）
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### Q2: 如何调试 LangGraph？

```python
# 打印每一步的状态
for step in app.stream(initial_state):
    print(step)
```

### Q3: 如何与 Spring Boot 通信？

Spring Boot 调用 Python 服务：
```java
// Java 端
WebClient client = WebClient.create("http://localhost:8000");
String result = client.post()
    .uri("/chat")
    .bodyValue(request)
    .retrieve()
    .bodyToMono(String.class)
    .block();
```

Python 端提供接口：
```python
@app.post("/chat")
def chat(request: ChatRequest):
    result = agent_graph.invoke(...)
    return {"reply": result["final_reply"]}
```

---

## 8. 已生成的迁移代码（当前仓库）

下面是已经在仓库中生成的 Python Agent 代码骨架，和 Java 代码的文件级映射。

### 8.1 Java → Python 文件映射

| Java 文件 | Python 文件 |
|-----------|-------------|
| `agent/service/AgentService.java` | `python-agent/app/main.py` |
| `agent/graph/config/AgentGraphConfiguration.java` | `python-agent/app/graph/builder.py` |
| `agent/graph/state/AgentStateFactory.java` | `python-agent/app/graph/state.py` |
| `agent/graph/node/PlannerNode.java` | `python-agent/app/graph/nodes/planner.py` |
| `agent/graph/node/DispatcherNode.java` | `python-agent/app/graph/nodes/dispatcher.py` |
| `agent/graph/node/SearchWorkerNode.java` | `python-agent/app/graph/nodes/search_worker.py` |
| `agent/graph/node/ChatWorkerNode.java` | `python-agent/app/graph/nodes/chat_worker.py` |
| `agent/graph/node/SynthesizerNode.java` | `python-agent/app/graph/nodes/synthesizer.py` |
| `agent/service/QueryRewriteService.java` | `python-agent/app/services/query_rewrite.py` |
| `agent/service/RerankerService.java` | `python-agent/app/services/reranker.py` |
| `agent/service/ZhipuEmbeddingService.java` | `python-agent/app/services/embedding.py` |
| `agent/component/EsVectorStore.java` + `component/EsComponent.java` | `python-agent/app/clients/es_client.py` |
| `component/RedisComponent.java` | `python-agent/app/clients/redis_client.py` |
| `agent/tool/ArticleTool.java` | `python-agent/app/tools/article_tool.py` |
| `agent/tool/BochaSearchTool.java` | `python-agent/app/tools/web_search.py` |

### 8.2 已生成目录结构

```text
python-agent/
├── .env.example
├── requirements.txt
└── app/
    ├── __init__.py
    ├── config.py
    ├── main.py
    ├── clients/
    │   ├── __init__.py
    │   ├── es_client.py
    │   └── redis_client.py
    ├── graph/
    │   ├── __init__.py
    │   ├── builder.py
    │   ├── state.py
    │   └── nodes/
    │       ├── __init__.py
    │       ├── planner.py
    │       ├── dispatcher.py
    │       ├── search_worker.py
    │       ├── chat_worker.py
    │       └── synthesizer.py
    ├── services/
    │   ├── __init__.py
    │   ├── embedding.py
    │   ├── query_rewrite.py
    │   └── reranker.py
    └── tools/
        ├── __init__.py
        ├── article_tool.py
        └── web_search.py
```

### 8.3 运行步骤（本地）

```bash
cd python-agent
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
# source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

uvicorn app.main:app --reload --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
```

### 8.4 下一步改造建议

1. 将 `embedding.py` 中的 hash 兜底实现替换为真实 Embedding API。
2. 将 `builder.py` 中 `analysis/writing` 占位节点替换为真实业务实现。
3. 将 Spring Boot `AgentService` 改为 HTTP 调用 Python Agent 服务。
4. 接入统一日志、链路追踪、异常告警（如 Sentry + OpenTelemetry）。
