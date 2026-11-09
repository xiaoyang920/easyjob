# 2026 Agent 技术扩展实战指南

> 基于 EasyJob Python Agent 现有架构，覆盖 5 大方向的落地代码  
> 每个方向标注 `🟢 可直接运行` / `🟡 需要配置` / `🔴 需要外部服务`  
> 所有代码均匹配现有项目的 async + LangGraph + FastAPI 风格

### 编码约定：结构化输出

本文档所有需要 LLM 返回 JSON 的场景，均使用 LangChain 的 **`with_structured_output()`** 而非手动 `json.loads()`：

```python
# ❌ 旧写法 —— 脆弱，需要处理 markdown 代码块、格式错误等
resp = await llm.ainvoke([...])
text = resp.content.strip()
if text.startswith("```"):
    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
data = json.loads(text)

# ✅ 新写法 —— 直接返回 Pydantic 对象，解析由框架完成
class MyResult(BaseModel):
    score: float = Field(description="评分")
    reason: str = Field(default="", description="原因")

structured_llm = llm.with_structured_output(MyResult, method="json_mode")
result = await structured_llm.ainvoke([...])  # result: MyResult 对象
print(result.score)  # 直接属性访问
```

> **⚠️ DeepSeek 兼容性**: 默认的 `method="function_calling"` 依赖 OpenAI function calling schema，  
> 但 DeepSeek API 不完整支持（`strict: true` 会报错）。必须显式指定 `method="json_mode"`，  
> 这样框架会把 Pydantic schema 注入 system prompt 并开启 `response_format={"type": "json_object"}`，DeepSeek 完整支持。

---

## 目录

| # | 方向 | 核心技术 | 难度 | 状态 |
|---|------|----------|------|------|
| 1 | [MCP 客户端集成](#1-mcp-客户端集成) | Model Context Protocol | ⭐⭐ | 🟡 |
| 2 | [长期记忆系统](#2-长期记忆系统) | Episodic + Semantic Memory | ⭐⭐⭐ | 🟢 |
| 3 | [Agent 可观测性](#3-agent-可观测性) | LangFuse Tracing | ⭐ | 🟡 |
| 4 | [反思循环工作流](#4-反思循环工作流) | Self-Reflection + Retry | ⭐⭐ | 🟢 |
| 5 | [Agentic RAG 升级](#5-agentic-rag-升级) | Adaptive Retrieval + Self-RAG | ⭐⭐⭐ | 🟢 |

---

## 现有架构快速回顾

```
FastAPI ──→ LangGraph StateGraph ──→ Redis Checkpointer
              │
              ├── planner_node (意图分析)
              ├── dispatcher_node (Send API 并行)
              ├── search_worker (RAG: QueryRewrite → 粗检索 → Rerank)
              ├── chat_worker (多轮对话)
              ├── analysis_worker (数据分析 + Tool)
              ├── writing_worker (写作 + interrupt 审批)
              └── synthesizer_node (结果汇总)

已有基础设施：
- ES (向量 + 全文)、Redis (session + checkpoint)、MySQL (会话持久化)
- Tool 体系：search_articles / search_articles_by_knn / web_search
- 通用 tool 循环：run_tool_agent()
- SSE 流式推送 + 进度协议
```

---

## 1. MCP 客户端集成

> **核心价值**：让 Agent 从"3 个硬编码工具"变成"动态发现和调用任意 MCP Server 的工具"  
> **2026 关键词**：MCP 是 Anthropic 发起的开放协议，已成为 Agent 工具互操作的事实标准

### 1.1 架构设计

```
现有架构                          MCP 扩展后
─────────                        ────────────
tools/                           tools/
  article_tool.py                  article_tool.py     (保留)
  web_search.py                    web_search.py       (保留)
                                 clients/
                                   mcp_client.py       ← 新增 MCP 客户端
                                 services/
                                   tool_registry.py    ← 新增 工具注册中心

Planner → Worker (硬编码3个工具)  →  Planner → Worker (动态 N 个工具)
```

### 1.2 新增依赖

```txt
# requirements.txt 追加
langchain-mcp-adapters>=0.2,<1.0
```

> `langchain-mcp-adapters` 是 LangChain 官方维护的 MCP 适配器，内部已封装：
> - `MultiServerMCPClient` — 同时连接多个 MCP Server（stdio / SSE / streamable-http）
> - `load_mcp_tools()` — 一行将 MCP 工具转为 LangChain Tool，直接 `bind_tools()`
> - 自动管理连接生命周期（async context manager）
>
> **不需要手写** `ClientSession` 管理、`call_tool` 封装、`StructuredTool.from_function` 转换。

### 1.3 新增文件：`app/clients/mcp_client.py`

```python
"""
MCP 客户端管理器
基于 langchain-mcp-adapters 官方库，直接获得 LangChain / LangGraph 兼容的工具

对应概念: Java 的 Spring AI MCP Client Auto-Configuration
"""
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool

log = logging.getLogger(__name__)


class McpClientManager:
    """
    封装 MultiServerMCPClient，管理生命周期 + 缓存工具列表

    用法:
        manager = McpClientManager()
        await manager.connect(server_configs)
        tools = manager.get_tools()        # → list[BaseTool], 直接给 bind_tools()
        await manager.shutdown()
    """

    def __init__(self):
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] = []

    async def connect(self, server_configs: dict):
        """
        连接所有 MCP Server 并缓存工具列表

        :param server_configs: MultiServerMCPClient 的配置字典，格式:
            {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "transport": "stdio",
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
                },
                "weather": {
                    "url": "http://localhost:8000/mcp",
                    "transport": "http",
                },
            }
        """
        if not server_configs:
            log.info("无 MCP Server 配置，跳过")
            return

        self._client = MultiServerMCPClient(server_configs)
        # get_tools() 内部会自动: 连接 → initialize → list_tools → 转 LangChain Tool
        self._tools = await self._client.get_tools()

        log.info(
            "MCP 已连接 %d 个 Server，共发现 %d 个工具: %s",
            len(server_configs),
            len(self._tools),
            [t.name for t in self._tools],
        )

    def get_tools(self) -> list[BaseTool]:
        """获取所有 MCP 工具（已经是 LangChain BaseTool，可直接 bind_tools）"""
        return self._tools

    async def reload(self, server_configs: dict):
        """
        热重载: 关闭旧连接 → 用新配置重新连接

        调用时机: POST /mcp/reload 接口，运行时改配置不用重启服务
        """
        log.info("MCP 热重载开始，关闭旧连接...")
        await self.shutdown()
        await self.connect(server_configs)
        log.info("MCP 热重载完成")

    async def shutdown(self):
        """关闭连接：必须调 __aexit__ 才能真正终止子进程和 session"""
        if self._client:
            await self._client.__aexit__(None, None, None)
        self._tools.clear()
        self._client = None
        log.info("MCP 连接已关闭")


# ─── 全局单例 ───
mcp_manager = McpClientManager()
```

> **对比原版**: 从 ~160 行 → ~50 行，去掉了手动的 `ClientSession` / `StdioServerParameters` /
> `sse_client` / `AsyncExitStack` / `StructuredTool.from_function` 等全部样板代码。
> `MultiServerMCPClient.get_tools()` 一个方法搞定所有事。

### 1.4 新增文件：`app/services/tool_registry.py`

```python
"""
工具注册中心
统一管理本地工具 + MCP 动态工具

对应概念: 把分散在各 worker 里的 AVAILABLE_TOOLS 统一收拢
"""
import logging
from langchain_core.tools import BaseTool

from app.tools.article_tool import search_articles, search_articles_by_knn
from app.tools.web_search import web_search
from app.clients.mcp_client import mcp_manager

log = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册中心

    用法:
        registry = ToolRegistry()
        await registry.refresh()  # 刷新 MCP 工具
        tools = registry.get_tools(["search_articles", "web_search", "mcp_xxx"])
    """

    def __init__(self):
        # 本地工具（手动注册）
        self._local_tools: dict[str, BaseTool] = {
            "search_articles": search_articles,
            "search_articles_by_knn": search_articles_by_knn,
            "web_search": web_search,
        }
        # MCP 动态工具
        self._mcp_tools: dict[str, BaseTool] = {}

    def refresh(self):
        """从 MCP Manager 刷新工具列表（同步，因为 get_tools() 只是读内存缓存）"""
        mcp_tools = mcp_manager.get_tools()
        self._mcp_tools = {t.name: t for t in mcp_tools}
        log.info(
            "工具注册中心: 本地 %d + MCP %d = 总计 %d",
            len(self._local_tools), len(self._mcp_tools),
            len(self._local_tools) + len(self._mcp_tools),
        )

    def get_all_tools(self) -> list[BaseTool]:
        """获取全部工具"""
        return list(self._local_tools.values()) + list(self._mcp_tools.values())

    def get_tools(self, names: list[str]) -> list[BaseTool]:
        """按名称获取指定工具"""
        merged = {**self._local_tools, **self._mcp_tools}
        return [merged[n] for n in names if n in merged]

    def get_tool_descriptions(self) -> str:
        """生成工具描述文本，注入给 Planner 做决策"""
        lines = []
        for name, tool in {**self._local_tools, **self._mcp_tools}.items():
            desc = tool.description.split("\n")[0] if tool.description else "无描述"
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)


# ─── 全局单例 ───
tool_registry = ToolRegistry()
```

### 1.5 修改 `app/config.py` — 新增 MCP 配置

```python
# === 追加到 Settings 类尾部 ===

    # MCP Server 配置（JSON 格式，从环境变量加载）
    # 直接用 MultiServerMCPClient 的字典格式，不需要自定义 dataclass
    MCP_SERVERS_JSON: str = os.getenv("MCP_SERVERS_JSON", "{}")
    # 格式示例:
    # {
    #   "github": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    #   "weather": {"transport": "http", "url": "http://localhost:8000/mcp"}
    # }
```

### 1.6 修改 `app/main.py` — 启动时连接 MCP

```python
# === lifespan 函数改造 ===

import json as _json
from app.clients.mcp_client import mcp_manager
from app.services.tool_registry import tool_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时连接 MySQL + MCP，关闭时断开"""
    await mysql_client.startup()

    # 连接 MCP Servers
    server_configs = _json.loads(settings.MCP_SERVERS_JSON)
    if server_configs:
        await mcp_manager.connect(server_configs)
        tool_registry.refresh()

    yield

    await mcp_manager.shutdown()
    await mysql_client.shutdown()
```

### 1.7 修改 Worker — 使用动态工具

以 `search_worker.py` 为例，其他 worker 同理：

```python
# === search_worker_node 函数内，替换 AVAILABLE_TOOLS 的使用 ===
# 原来:
#   from app.tools.web_search import web_search
#   AVAILABLE_TOOLS = [web_search, search_articles, search_articles_by_knn]
# 改为:

from app.services.tool_registry import tool_registry

# 在 search_worker_node 内:
async def search_worker_node(state: AgentState) -> dict:
    # ... 省略不变的代码 ...

    # 动态获取工具（包含本地 + MCP 工具）
    all_tools = tool_registry.get_all_tools()

    reply = await run_tool_agent(
        system_prompt=SEARCH_SYSTEM_PROMPT.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        ),
        user_input=f"任务：{task_input}\n\nRAG 参考资料：\n{rag_context}",
        tools=all_tools,  # ← 改这里
        max_rounds=2,
    )
    # ... 其余不变 ...
```

### 1.8 新增 API：工具列表查询

```python
# === app/main.py 追加 ===

@app.get("/tools")
async def list_tools():
    """查看当前 Agent 可用的所有工具（本地 + MCP）"""
    from app.services.tool_registry import tool_registry
    tools = tool_registry.get_all_tools()
    return [{"name": t.name, "description": t.description} for t in tools]


class McpReloadRequest(BaseModel):
    """MCP 热重载请求，传入新的 server 配置"""
    servers: dict  # 和 MCP_SERVERS_JSON 格式一致

@app.post("/mcp/reload")
async def reload_mcp(request: McpReloadRequest):
    """
    运行时热重载 MCP 配置，不用重启服务

    流程: 关闭旧连接 → 用新配置连接 → 刷新 tool_registry
    """
    from app.clients.mcp_client import mcp_manager
    from app.services.tool_registry import tool_registry

    await mcp_manager.reload(request.servers)
    tool_registry.refresh()

    tools = tool_registry.get_all_tools()
    return {
        "status": "ok",
        "tool_count": len(tools),
        "tools": [t.name for t in tools],
    }
```

### 1.9 与 LangGraph StateGraph 的结合方式

`langchain-mcp-adapters` 官方文档给出了 LangGraph 集成示例，
但我们项目用了自定义图结构（不是 `ToolNode` 预构建模式），所以集成方式是：

```python
# 官方 prebuilt 方式（适合简单场景，我们没用这个）:
from langgraph.prebuilt import ToolNode, tools_condition
builder.add_node(ToolNode(tools))
builder.add_conditional_edges("call_model", tools_condition)

# 我们的方式: MCP 工具通过 tool_registry 进入 run_tool_agent 循环
# MCP Tool 已经是标准 BaseTool → bind_tools() 和 ainvoke() 完全兼容
# 不需要改 run_tool_agent 的任何代码！
```

### 1.10 .env 配置示例

```env
# 方式一: 不配 MCP，保持原有行为（注意是空对象 {}，不是空数组）
MCP_SERVERS_JSON={}

# 方式二: 连接 GitHub MCP Server（stdio 传输）
MCP_SERVERS_JSON={"github":{"transport":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-github"],"env":{"GITHUB_PERSONAL_ACCESS_TOKEN":"ghp_xxx"}}}

# 方式三: 连接远程天气服务（streamable-http 传输）
MCP_SERVERS_JSON={"weather":{"transport":"http","url":"http://localhost:8000/mcp"}}

# 方式四: 同时连接多个（stdio + http 混合）
MCP_SERVERS_JSON={"github":{"transport":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-github"]},"weather":{"transport":"http","url":"http://localhost:8000/mcp"}}
```

### 1.11 用户级工具隔离

> **为什么不能每个用户一套子进程？**  
> MCP stdio 传输 = 每连一个 Server 启动一个子进程。  
> 1000 用户 × 3 个 Server = 3000 个进程，内存直接爆。  
> 即使用 HTTP 传输，1000 个持久连接也是资源浪费。

#### 架构：平台共享 + 用户权限过滤

```
┌─────────────────────────────────────────────────┐
│              McpClientManager (全局单例)           │
│    平台级 MCP Servers（启动时连接，所有用户共享）    │
│    github / web-search / db-query / ...          │
│    发现工具: [create_issue, web_search, ...]      │
└──────────────────────┬──────────────────────────┘
                       │ get_tools() → 全量工具
                       ↓
┌─────────────────────────────────────────────────┐
│              ToolRegistry (全局单例)               │
│    get_tools_for_user(user_id)                   │
│      → 查 user_tool_permission 表                 │
│      → 过滤出该用户有权限的工具子集                 │
└──────────────────────┬──────────────────────────┘
                       │ → [web_search, create_issue]  (用户 A)
                       │ → [web_search]                (用户 B, 没配 github)
                       ↓
                  Worker 节点使用
```

#### 数据库表

```sql
-- 用户工具权限表
CREATE TABLE user_tool_permission (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id     BIGINT NOT NULL,
    tool_name   VARCHAR(100) NOT NULL COMMENT '工具名，如 create_issue / web_search',
    enabled     TINYINT DEFAULT 1 COMMENT '1=启用 0=禁用',
    config_json TEXT COMMENT '用户级配置（如 GitHub Token），加密存储',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_tool (user_id, tool_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户工具权限';
```

#### ToolRegistry 加一个方法

```python
# === app/services/tool_registry.py 追加 ===

from app.clients.mysql_client import db

class ToolRegistry:
    # ... 保留已有代码 ...

    async def get_tools_for_user(self, user_id: int) -> list[BaseTool]:
        """
        获取该用户有权限的工具子集

        流程:
        1. 查 user_tool_permission 表
        2. 没有记录 → 返回默认工具（本地 3 个）
        3. 有记录 → 只返回 enabled=1 的工具
        """
        rows = await db.fetch_all(
            "SELECT tool_name FROM user_tool_permission WHERE user_id = :uid AND enabled = 1",
            {"uid": user_id},
        )

        if not rows:
            # 没配过权限 → 返回默认本地工具（安全默认值）
            return list(self._local_tools.values())

        allowed_names = {r._mapping["tool_name"] for r in rows}
        merged = {**self._local_tools, **self._mcp_tools}
        return [merged[n] for n in allowed_names if n in merged]
```

#### Worker 改用 user_id 过滤

```python
# === search_worker_node 内 ===
# 前提: AgentState 里已经有 user_id（从 main.py 传入）

async def search_worker_node(state: AgentState) -> dict:
    # ...
    user_id = state.get("user_id")
    if user_id:
        all_tools = await tool_registry.get_tools_for_user(user_id)
    else:
        all_tools = tool_registry.get_all_tools()
    # ...
```

#### （进阶）用户自带 MCP Server 的连接池

如果真有场景需要用户接入**自己的私有 MCP Server**（比如私有数据库），
用按需连接 + LRU 超时回收，不要常驻：

```python
"""
用户级 MCP 连接池（仅用于用户自带 MCP Server 的高级场景）
"""
import asyncio
import time
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient

log = logging.getLogger(__name__)

# 连接池参数
MAX_USER_CONNECTIONS = 50   # 全局最多同时保持 50 个用户连接
IDLE_TIMEOUT = 300          # 5 分钟没用就回收


class UserMcpPool:
    """
    按需创建 + LRU 超时回收的用户级 MCP 连接池

    为什么不用全局 McpClientManager:
    - 平台级 Server 数量固定（5-10个），适合常驻
    - 用户私有 Server 数量不可控，必须按需创建 + 回收
    """

    def __init__(self):
        self._pool: dict[int, dict] = {}
        # 结构: {user_id: {"client": MultiServerMCPClient, "tools": [...], "last_access": timestamp}}
        self._lock = asyncio.Lock()

    async def get_tools(self, user_id: int, server_configs: dict) -> list:
        """
        获取用户的 MCP 工具（按需连接，有缓存）
        """
        async with self._lock:
            now = time.time()

            # 命中缓存
            if user_id in self._pool:
                entry = self._pool[user_id]
                entry["last_access"] = now
                return entry["tools"]

            # 超过上限，先淘汰最久没用的
            if len(self._pool) >= MAX_USER_CONNECTIONS:
                await self._evict_oldest()

            # 新建连接
            client = MultiServerMCPClient(server_configs)
            tools = await client.get_tools()

            self._pool[user_id] = {
                "client": client,
                "tools": tools,
                "last_access": now,
            }
            log.info("用户 %d MCP 连接已建立, 工具数: %d", user_id, len(tools))
            return tools

    async def _evict_oldest(self):
        """淘汰最久没访问的连接"""
        if not self._pool:
            return
        oldest_uid = min(self._pool, key=lambda uid: self._pool[uid]["last_access"])
        entry = self._pool.pop(oldest_uid)
        client = entry["client"]
        if client:
            await client.__aexit__(None, None, None)
        log.info("回收用户 %d 的 MCP 连接（空闲淘汰）", oldest_uid)

    async def cleanup_idle(self):
        """清理超时空闲连接（定时任务调用）"""
        now = time.time()
        expired = [
            uid for uid, entry in self._pool.items()
            if now - entry["last_access"] > IDLE_TIMEOUT
        ]
        for uid in expired:
            entry = self._pool.pop(uid)
            client = entry["client"]
            if client:
                await client.__aexit__(None, None, None)
            log.info("回收用户 %d 的 MCP 连接（超时）", uid)

    async def shutdown(self):
        """关闭所有用户连接"""
        for uid, entry in self._pool.items():
            client = entry["client"]
            if client:
                await client.__aexit__(None, None, None)
        self._pool.clear()


user_mcp_pool = UserMcpPool()
```

#### 选择建议

| 场景 | 方案 | 复杂度 |
|------|------|--------|
| 所有用户用同一批工具 | 当前方案（全局单例）就够 | ⭐ |
| 不同用户能用不同工具 | **平台共享 + 权限表过滤**（推荐先做这个） | ⭐⭐ |
| 用户能接入自己的 MCP Server | 权限表 + UserMcpPool 连接池 | ⭐⭐⭐ |

> **建议**：先做"权限表过滤"就足够了，只加一张表 + 一个查询方法。
> 连接池方案留在真正有用户提出"我要接自己的私有数据库"需求时再做。

### 1.12 学到了什么

| 技术点 | 说明 |
|--------|------|
| `langchain-mcp-adapters` | LangChain 官方 MCP 适配库，一行 `get_tools()` 搞定所有转换 |
| `MultiServerMCPClient` | 同时管理多个 MCP Server，支持 stdio / SSE / streamable-http 三种传输 |
| MCP 工具 = LangChain Tool | 转换后的工具直接兼容 `bind_tools()`, `run_tool_agent()`, `ToolNode` |
| 注册中心模式 | 解耦工具来源（本地 vs MCP），Worker 不关心工具从哪来 |
| 框架优先原则 | **先查框架有没有现成的**，再决定是否手写——避免重复造轮子 |
| 多租户工具隔离 | 平台共享连接 + 权限表过滤，不要每个用户起子进程 |
| 连接池模式 | 按需创建 + LRU 淘汰 + 超时回收，控制资源上限 |

---

## 2. 长期记忆系统

> **核心价值**：让 Agent 记住用户跨会话的偏好和历史，对话越来越"懂你"  
> **2026 关键词**：MemGPT/Letta 分层记忆架构，已成为有状态 Agent 标配

### 2.1 架构设计

```
现有记忆                              扩展后
─────────                             ────────
ConversationService                   ConversationService (不变)
  ├── session history (MySQL)           ├── session history (MySQL, 不变)
  └── summary compression              └── summary compression (不变)
                                      
                                      MemoryService ← 新增
                                        ├── Episodic Memory (事件记忆)
                                        │   "用户上周问过 Spring Boot 3 升级"
                                        │   → MySQL: user_memory 表
                                        │
                                        ├── Semantic Memory (语义记忆)
                                        │   "用户是 Java 后端开发, 偏好实战内容"
                                        │   → MySQL: user_profile 表
                                        │
                                        └── Memory Retrieval (记忆检索)
                                            当前对话时自动召回相关记忆
                                            → ES 向量搜索 user_memories 索引
```

### 2.2 数据库表设计

```sql
-- 事件记忆（Episodic Memory）
CREATE TABLE user_memory (
    memory_id    BIGINT PRIMARY KEY COMMENT '雪花ID',
    user_id      BIGINT NOT NULL,
    content      TEXT NOT NULL COMMENT '记忆内容（仅事件记忆，语义事实写 user_profile）',
    importance   FLOAT DEFAULT 0.5 COMMENT '重要性 0-1, 用于遗忘策略',
    access_count INT DEFAULT 0 COMMENT '被召回次数',
    source_conversation_id BIGINT COMMENT '来源会话ID',
    create_time  DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_importance (user_id, importance DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户事件记忆（Episodic Memory）';

-- 用户画像（Semantic Memory）
CREATE TABLE user_profile (
    user_id       BIGINT PRIMARY KEY,
    tech_stack    JSON COMMENT '技术栈偏好 ["Java","Spring Boot","Python"]',
    interests     JSON COMMENT '兴趣领域 ["后端开发","微服务","AI"]',
    experience    VARCHAR(20) DEFAULT 'unknown' COMMENT 'junior|mid|senior',
    preferences   JSON COMMENT '对话偏好 {"style":"practical","detail":"high"}',
    summary       TEXT COMMENT 'LLM 生成的综合画像摘要',
    create_time   DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户语义画像';
```

### 2.3 ES 向量索引（记忆检索用）

```json
PUT user_memories
{
  "settings": { "number_of_shards": 1, "number_of_replicas": 0 },
  "mappings": {
    "properties": {
      "memory_id":  { "type": "long" },
      "user_id":    { "type": "long" },
      "content":    { "type": "text", "analyzer": "ik_max_word" },
      "content_vector": {
        "type": "dense_vector",
        "dims": 2048,
        "index": true,
        "similarity": "cosine"
      },
      "importance":  { "type": "float" },
      "create_time": { "type": "date" }
    }
  }
}
```

### 2.4 新增文件：`app/services/memory.py`

```python
"""
长期记忆服务
实现 Episodic Memory + Semantic Memory + Memory Retrieval

对应概念: MemGPT/Letta 的分层记忆架构
"""
import json
import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.clients.mysql_client import db
from app.clients.es_client import BaseEsClient
from app.config import get_llm
from app.services.embedding import EmbeddingService
from app.utils.snowflake import snowflake

log = logging.getLogger(__name__)


# ─── 结构化输出 Model（LLM 提取结果的 schema，不是 DB 行结构）───
# memory_id / user_id / access_count / create_time 等由应用代码插入时添加，不需要 LLM 输出
class MemoryItem(BaseModel):
    content: str = Field(description="记忆内容")
    importance: float = Field(default=0.5, description="重要性 0-1")
    # 注: 不需要 type 字段——episodic 事件写这里，semantic 事实写入 profile_updates。
    #      分离已经由 MemoryExtractResult 的结构实现，不需要字段区分。


class ProfileUpdates(BaseModel):
    tech_stack: list[str] = Field(default_factory=list, description="识别到的技术栈")
    interests: list[str] = Field(default_factory=list, description="识别到的兴趣")
    experience: Optional[str] = Field(default=None, description="junior|mid|senior，无法判断则不填")
    preferences: dict = Field(default_factory=dict, description="对话偏好，如 {\"style\": \"practical\", \"detail\": \"high\"}")


class MemoryExtractResult(BaseModel):
    memories: list[MemoryItem] = Field(default_factory=list)
    profile_updates: ProfileUpdates = Field(default_factory=ProfileUpdates)


# ─── 记忆提取 Prompt ───
MEMORY_EXTRACT_PROMPT = """分析以下对话，提取值得长期记住的信息。

【两种记忆的区别】
- memories（事件记忆）: 具体发生了什么，如"用户今天问了 Spring Boot 升级问题"
- profile_updates（用户画像）: 关于用户本身的持久事实，如技术栈、经验水平、兴趣

【提取规则】
1. 具体的对话事件/结论 → 放入 memories
2. 用户的技术栈/兴趣/经验等背景信息 → 放入 profile_updates
3. 不要提取临时性、一次性的信息

【对话内容】
{conversation}"""
# † JSON schema 由 with_structured_output(MemoryExtractResult) 自动注入，无需在 prompt 里手写格式

# ─── 记忆个性化 Prompt（注入给 Worker） ───
MEMORY_CONTEXT_TEMPLATE = """[用户画像]
{profile_summary}

[相关历史记忆]
{relevant_memories}"""


class MemoryService:
    """
    长期记忆管理

    核心流程:
    1. 对话结束后 → extract_and_store() 提取记忆
    2. 新对话开始时 → recall() 召回相关记忆
    3. 定期 → decay() 遗忘不重要的记忆
    """

    def __init__(self):
        self._embedding = EmbeddingService()
        self._es = BaseEsClient()
        self._llm = get_llm(temperature=0.3)

    # ─────────────── 记忆提取 ───────────────

    async def extract_and_store(
        self, user_id: int, conversation_id: int, messages: list[dict]
    ):
        """
        从一次对话中提取记忆并存储

        调用时机: 对话结束后异步执行（不阻塞响应）
        """
        if len(messages) < 4:
            return  # 太短的对话不提取

        # 构建对话文本
        conv_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages[-20:]  # 最多取最近 20 条
        )

        try:
            structured_llm = self._llm.with_structured_output(MemoryExtractResult, method="json_mode")
            data = await structured_llm.ainvoke([
                SystemMessage(content=MEMORY_EXTRACT_PROMPT.format(conversation=conv_text))
            ])
            # data 已经是 MemoryExtractResult 对象，不需要 json.loads
        except Exception as e:
            log.warning("记忆提取失败: %s", e)
            return

        # 存储 episodic 事件记忆（批量写入）
        episodic = [m for m in data.memories]  # 已无 type 字段，全部是 episodic
        if episodic:
            await self._store_memories(
                user_id=user_id,
                memories=episodic,
                source_conversation_id=conversation_id,
            )
        
        # 更新用户画像
        profile_updates = data.profile_updates
        if profile_updates and any([profile_updates.tech_stack, profile_updates.interests,
                                      profile_updates.experience, profile_updates.preferences]):
            await self._update_profile(user_id, profile_updates)

    async def _store_memories(
        self,
        user_id: int,
        memories: list[MemoryItem],
        source_conversation_id: int | None = None,
    ):
        """批量存储事件记忆到 MySQL + ES"""
        if not memories:
            return

        now = datetime.now()
        # 预生成所有 ID， MySQL 和 ES 共用
        rows = [
            {
                "mid": snowflake.next_id(),
                "uid": user_id,
                "content": m.content,
                "imp": m.importance,
                "src_conv": source_conversation_id,
                "now": now,
            }
            for m in memories
        ]

        # ─── MySQL 批量插入 ───
        await db.execute_many(
            """
            INSERT INTO user_memory
                (memory_id, user_id, content, importance,
                 source_conversation_id, create_time, update_time)
            VALUES
                (:mid, :uid, :content, :imp, :src_conv, :now, :now)
            """,
            rows,
        )

        # ─── ES 批量写入 ───
        # 一次 API 请求批量 embed（比 asyncio.gather 发 N 个请求更高效）
        try:
            vectors = await self._embedding.aembed_batch([r["content"] for r in rows])

            # helpers.async_bulk 要求一个 action 生成器
            # 每条 action 用 "_index" 操作表示 upsert
            actions = [
                {
                    "_index": "user_memories",
                    "_id": str(r["mid"]),
                    "_source": {
                        "memory_id": r["mid"],
                        "user_id": r["uid"],
                        "content": r["content"],
                        "content_vector": vec,
                        "importance": r["imp"],
                        "create_time": now.isoformat(),
                    },
                }
                for r, vec in zip(rows, vectors)
            ]

            from elasticsearch.helpers import async_bulk
            ok, errors = await async_bulk(self._es.client, actions, raise_on_error=False)
            if errors:
                log.warning("记忆写入 ES 部分失败: %s", errors)
            else:
                log.info("批量写入 ES: user=%s, count=%d", user_id, ok)
        except Exception as e:
            log.warning("记忆批量写入 ES 失败: %s", e)

        log.info("存储记忆: user=%s, count=%d", user_id, len(rows))



    async def recall(self, user_id: int, query: str, top_k: int = 5) -> str:
        """
        根据当前问题召回相关记忆

        返回格式化字符串，直接注入给 LLM 作为上下文
        """
        # 1. 向量检索相关记忆
        relevant_memories = await self._search_memories(user_id, query, top_k)

        # 2. 获取用户画像
        profile = await self._get_profile(user_id)
        profile_summary = profile.get("summary", "暂无用户画像") if profile else "新用户，暂无画像"

        # 3. 更新访问计数（被召回的记忆更难被遗忘）
        if relevant_memories:
            ids = [m["memory_id"] for m in relevant_memories]
            placeholders = ",".join(str(i) for i in ids)
            await db.execute(
                f"UPDATE user_memory SET access_count = access_count + 1 WHERE memory_id IN ({placeholders})"
            )

        # 4. 格式化输出
        if not relevant_memories:
            mem_text = "无相关历史记忆"
        else:
            mem_text = "\n".join(
                f"- {m['content']} (重要性: {m['importance']:.1f})"
                for m in relevant_memories
            )

        return MEMORY_CONTEXT_TEMPLATE.format(
            profile_summary=profile_summary,
            relevant_memories=mem_text,
        )

    async def _search_memories(
        self, user_id: int, query: str, top_k: int = 5
    ) -> list[dict]:
        """向量搜索用户记忆"""
        try:
            query_vector = await self._embedding.aembed(query)
            resp = await self._es.client.search(
                index="user_memories",
                knn={
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": top_k * 3,
                    "filter": {"term": {"user_id": user_id}},
                },
                size=top_k,
            )
            results = []
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit["_source"]
                src["score"] = hit["_score"]
                results.append(src)
            return results
        except Exception as e:
            log.warning("记忆检索失败: %s", e)
            return []

    # ─────────────── 用户画像 ───────────────

    async def _get_profile(self, user_id: int) -> dict | None:
        """获取用户画像"""
        row = await db.fetch_one(
            "SELECT * FROM user_profile WHERE user_id = :uid",
            {"uid": user_id},
        )
        if not row:
            return None
        return dict(row._mapping)

    async def _update_profile(self, user_id: int, updates: ProfileUpdates):
        """增量更新用户画像（接收 Pydantic ProfileUpdates 对象）"""
        profile = await self._get_profile(user_id)

        if profile is None:
            # 新建
            await db.execute(
                """
                INSERT INTO user_profile (user_id, tech_stack, interests, experience, preferences, create_time, update_time)
                VALUES (:uid, :ts, :it, :exp, :pref, :now, :now)
                """,
                {
                    "uid": user_id,
                    "ts": json.dumps(updates.tech_stack, ensure_ascii=False),
                    "it": json.dumps(updates.interests, ensure_ascii=False),
                    "exp": updates.experience or "unknown",
                    "pref": json.dumps(updates.preferences, ensure_ascii=False),
                    "now": datetime.now(),
                },
            )
        else:
            # 增量合并（列表去重合并，字符串取新值）
            old_stack = json.loads(profile.get("tech_stack") or "[]")
            old_interests = json.loads(profile.get("interests") or "[]")
            old_pref = json.loads(profile.get("preferences") or "{}")

            new_stack = list(set(old_stack + updates.tech_stack))
            new_interests = list(set(old_interests + updates.interests))
            new_exp = updates.experience or profile.get("experience", "unknown")
            new_pref = {**old_pref, **updates.preferences}  # 新属性覆盖旧的

            await db.execute(
                """
                UPDATE user_profile 
                SET tech_stack = :ts, interests = :it, experience = :exp,
                    preferences = :pref, update_time = :now
                WHERE user_id = :uid
                """,
                {
                    "uid": user_id,
                    "ts": json.dumps(new_stack, ensure_ascii=False),
                    "it": json.dumps(new_interests, ensure_ascii=False),
                    "exp": new_exp,
                    "pref": json.dumps(new_pref, ensure_ascii=False),
                    "now": datetime.now(),
                },
            )

        # 重新生成画像摘要
        await self._regenerate_summary(user_id)

    async def _regenerate_summary(self, user_id: int):
        """用 LLM 重新生成用户画像摘要"""
        profile = await self._get_profile(user_id)
        if not profile:
            return

        prompt = f"""根据以下用户数据生成一句话画像摘要:
技术栈: {profile.get('tech_stack', '[]')}
兴趣: {profile.get('interests', '[]')}
经验: {profile.get('experience', 'unknown')}
生成简洁的一句话描述（不超过50字）:"""

        try:
            resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
            summary = resp.content.strip()
            await db.execute(
                "UPDATE user_profile SET summary = :s, update_time = :now WHERE user_id = :uid",
                {"s": summary, "now": datetime.now(), "uid": user_id},
            )
        except Exception as e:
            log.warning("画像摘要生成失败: %s", e)

    # ─────────────── 记忆遗忘 ───────────────

    async def decay(self, user_id: int, decay_factor: float = 0.95):
        """
        记忆衰减：降低长期未访问记忆的重要性

        调用时机: 定时任务（如每天一次）
        衰减策略: importance *= decay_factor（被频繁召回的记忆不衰减）
        """
        await db.execute(
            """
            UPDATE user_memory 
            SET importance = importance * :factor, update_time = :now
            WHERE user_id = :uid 
              AND access_count < 3
              AND importance > 0.1
            """,
            {"factor": decay_factor, "now": datetime.now(), "uid": user_id},
        )

        # 删除重要性过低的记忆（真正的"遗忘"）
        await db.execute(
            "DELETE FROM user_memory WHERE user_id = :uid AND importance < 0.1",
            {"uid": user_id},
        )
        log.info("记忆衰减完成: user=%s, factor=%.2f", user_id, decay_factor)


# ─── 全局单例 ───
memory_service = MemoryService()
```

### 2.5 集成到现有流程

在 `app/main.py` 的 `/chat/stream` 接口中注入记忆：

```python
# === chat_stream 函数内，构建 initial_state 之前 ===

from app.services.memory import memory_service

# 召回长期记忆
memory_context = await memory_service.recall(request.user_id, processed_message)

# 把记忆作为 system 级上下文插入 history 最前面
if memory_context and "暂无" not in memory_context:
    context.insert(0, {"role": "system", "content": memory_context})

# === chat_stream 函数结尾，保存消息后，异步提取记忆 ===

import asyncio

# 异步提取记忆（不阻塞响应）
all_messages = await conversation_service.get_context_for_llm(conv_id)
asyncio.create_task(
    memory_service.extract_and_store(request.user_id, conv_id, all_messages)
)
```

### 2.6 新增 State 字段（可选，让 Planner 用上记忆）

```python
# === app/graph/state.py 追加字段 ===

class AgentState(TypedDict):
    # ... 现有字段 ...
    
    # 长期记忆上下文（注入给各 worker 参考）
    memory_context: str
```

### 2.7 学到了什么

| 技术点 | 说明 |
|--------|------|
| Episodic Memory | 事件记忆，记录具体交互事实，按时间衰减 |
| Semantic Memory | 语义记忆，抽象为用户画像，持久不衰减 |
| 记忆提取 | 用 LLM 后处理对话，提取值得记忆的信息 |
| 记忆召回 | 向量检索相关记忆，注入当前对话上下文 |
| 遗忘策略 | importance 衰减 + access_count 保护 + 阈值清理 |
| 异步提取 | `asyncio.create_task()` 不阻塞用户响应 |

---

## 3. Agent 可观测性

> **核心价值**：知道你的 Agent 每一步在做什么、花了多少钱、哪里慢  
> **2026 关键词**：LLMOps 从可选变为必备，LangFuse / LangSmith 是主流方案

### 3.1 架构设计

```
现有链路                              加入可观测性后
─────────                             ────────────────
FastAPI → LangGraph → LLM            FastAPI → LangGraph → LLM
  (看不到中间过程)                       │
                                      LangFuse / LangSmith Callback
                                        │
                                      ┌──┴──────────────────────┐
                                      │   Trace Dashboard       │
                                      │   ├── Planner (250ms, $0.003)    │
                                      │   ├── SearchWorker               │
                                      │   │   ├── QueryRewrite (180ms)   │
                                      │   │   ├── ES Search (50ms)       │
                                      │   │   ├── Rerank (200ms)         │
                                      │   │   └── LLM + Tools (800ms)   │
                                      │   ├── ChatWorker (400ms)         │
                                      │   └── Synthesizer (600ms)        │
                                      └─────────────────────────┘
```

### 3.2 新增依赖

```txt
# requirements.txt 追加（二选一）
# 方案 A: LangFuse（开源可自托管）
langfuse>=3.0,<4.0

# 方案 B: LangSmith（LangChain 官方）
# langsmith>=0.3,<1.0
```

### 3.3 新增文件：`app/services/observability.py`

```python
"""
可观测性服务
集成 LangFuse v3 实现全链路追踪

对应概念: Java 的 Spring Boot Actuator + Micrometer + Jaeger

LangFuse v3 与 v2 的关键变化:
- CallbackHandler 移至 langfuse.langchain 包
- 手动 Trace API (lf.trace().span()) 被 @observe 装饰器取代
- 自动读取 LANGFUSE_* 环境变量，无需显式传 key
"""
import logging
from functools import wraps

log = logging.getLogger(__name__)


def get_langfuse_callback():
    """
    获取 LangFuse v3 的 LangChain Callback Handler

    自动读取环境变量: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
    未安装或环境变量未配置时静默返回 None

    用于注入 LLM 调用链: llm.ainvoke(messages, config={"callbacks": [cb]})
    """
    try:
        from langfuse.langchain import CallbackHandler  # v3 路径（v2 是 langfuse.callback）
        return CallbackHandler()  # 自动读取 LANGFUSE_* 环境变量
    except ImportError:
        log.warning("langfuse 未安装，LLM 调用追踪禁用")
        return None
    except Exception as e:
        log.warning("LangFuse Callback 初始化失败: %s", e)
        return None


def trace_node(node_name: str):
    """
    节点级别装饰器，使用 LangFuse v3 @observe 自动追踪

    @observe 会自动记录: 函数入参、返回值、耗时、异常
    未安装 langfuse 时静默降级（直接调用原函数）

    用法:
        @trace_node("planner")
        async def planner_node(state: AgentState) -> dict:
            ...
    """
    def decorator(func):
        try:
            from langfuse import observe
            # observe 支持 async 函数，自动关联父 trace
            return observe(name=node_name)(func)
        except ImportError:
            return func  # 未安装则直接返回原函数，无任何副作用
    return decorator


class CostTracker:
    """
    Token/费用追踪器
    在 run_tool_agent 的每次 LLM 调用后统计

    用法:
        tracker = CostTracker()
        tracker.add_usage(model="deepseek-chat", prompt_tokens=500, completion_tokens=200)
        print(tracker.summary())
    """

    # 主流模型定价 ($/1K tokens)，2026年价格
    PRICING = {
        "deepseek-chat": {"prompt": 0.00014, "completion": 0.00028},
        "glm-4.6v": {"prompt": 0.001, "completion": 0.001},
    }

    def __init__(self):
        self._records: list[dict] = []

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int):
        pricing = self.PRICING.get(model, {"prompt": 0.001, "completion": 0.001})
        cost = (
            prompt_tokens / 1000 * pricing["prompt"]
            + completion_tokens / 1000 * pricing["completion"]
        )
        self._records.append({
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(cost, 6),
        })

    def summary(self) -> dict:
        total_prompt = sum(r["prompt_tokens"] for r in self._records)
        total_completion = sum(r["completion_tokens"] for r in self._records)
        total_cost = sum(r["cost_usd"] for r in self._records)
        return {
            "total_calls": len(self._records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_cost_usd": round(total_cost, 6),
            "details": self._records,
        }
```

### 3.4 集成到 `run_tool_agent` — 自动追踪每次 LLM 调用

```python
# === app/graph/tool_executor.py 修改 ===

from app.services.observability import get_langfuse_callback

async def run_tool_agent(
    system_prompt: str,
    user_input: str,
    tools: list[BaseTool] | None = None,
    max_rounds: int = 2,
    history_messages: list[BaseMessage] | None = None,
) -> str:
    llm = get_llm()
    tool_map = {t.name: t for t in tools} if tools else {}

    if tools:
        llm_bound = llm.bind_tools(tools)
    else:
        llm_bound = llm

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    if history_messages:
        messages.extend(history_messages)
    messages.append(HumanMessage(content=user_input))

    # LangFuse v3 Callback（未安装时自动降级为 None）
    callbacks = []
    lf_cb = get_langfuse_callback()
    if lf_cb:
        callbacks.append(lf_cb)

    for _ in range(max_rounds):
        response = await llm_bound.ainvoke(messages, config={"callbacks": callbacks})

        if not response.tool_calls:
            return response.content

        messages.append(response)
        for tc in response.tool_calls:
            fn = tool_map.get(tc["name"])
            if fn:
                result = await fn.ainvoke(tc["args"])
                # 注: Tool 调用的 span 由 @observe 装饰的父节点自动包含
            else:
                result = f"工具 {tc['name']} 不存在"
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    response = await llm_bound.ainvoke(messages, config={"callbacks": callbacks})
    return response.content
```

### 3.5 给节点加上 Trace 装饰器

```python
# === 改造各 node，只需加一行装饰器 ===

# app/graph/nodes/planner.py
from app.services.observability import trace_node

@trace_node("planner")
async def planner_node(state: AgentState) -> dict:
    # ... 原有代码不变 ...

# app/graph/nodes/search_worker.py
@trace_node("search_worker")
async def search_worker_node(state: AgentState) -> dict:
    # ... 原有代码不变 ...

# app/graph/nodes/synthesizer.py
@trace_node("synthesizer")
async def synthesizer_node(state: AgentState) -> dict:
    # ... 原有代码不变 ...

# 其他 worker 同理
```

### 3.6 .env 配置

```env
# LangFuse 配置（注册 https://cloud.langfuse.com 获取）
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_HOST=https://cloud.langfuse.com

# 或者自托管 LangFuse:
# LANGFUSE_HOST=http://localhost:3000
```

### 3.7 学到了什么

| 技术点 | 说明 |
|--------|------|
| LLMOps | 跟 DevOps/MLOps 同级，Agent 运维的标准实践 |
| Trace | 一次请求的全链路追踪，包含每个节点的耗时和结果 |
| Span | Trace 内的细粒度步骤（如单次 LLM 调用、Tool 调用） |
| Callback 机制 | LangChain 的 Callback 系统可无侵入式注入追踪 |
| 成本估算 | 按模型定价 × token 数算费用，生产环境必备 |

---

## 4. 反思循环工作流

> **核心价值**：Agent 输出质量差时能自我纠正，不再"一条路走到黑"  
> **2026 关键词**：Reflection / Self-Critique 已成为高质量 Agent 标配

### 4.1 架构设计

```
现有工作流（线性）                     加入反思循环后
─────────────────                     ──────────────────
Planner →                            Planner →
  Worker(s) →                          Worker(s) →
    Synthesizer →                        Reflector (新增) →
      END                                  ├── 质量 OK → Synthesizer → END
                                           └── 质量差 → 回到 Worker 重做
                                                         (最多重试 1 次)
```

### 4.2 新增文件：`app/graph/nodes/reflector.py`

```python
"""
反思节点
评估 Worker 输出质量，决定是否需要重做

对应概念: Self-Reflection / Critique Pattern
"""
import logging

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import get_llm
from app.graph.state import AgentState

log = logging.getLogger(__name__)


# ─── 结构化输出 Model ───
class ReflectScores(BaseModel):
    relevance: int = Field(description="相关性 0-10")
    completeness: int = Field(description="完整性 0-10")
    accuracy: int = Field(description="准确性 0-10")
    format: int = Field(description="格式性 0-10")


class ReflectResult(BaseModel):
    scores: ReflectScores
    overall: float = Field(description="综合得分")
    passed: bool = Field(description="是否通过, overall >= 6.0 且无严重错误时 true")
    feedback: str = Field(default="", description="具体的改进建议")


REFLECT_PROMPT = """你是一个质量评审专家。请评估以下 Agent 回复的质量。

【评估维度】
1. 相关性：回复是否切中用户问题（0-10）
2. 完整性：是否遗漏关键信息（0-10）
3. 准确性：事实和代码是否正确（0-10）
4. 格式性：结构是否清晰（0-10）

【用户问题】
{user_message}

【Agent 回复】
{agent_reply}

评分 >= 6.0 且没有严重事实错误时 passed=true，否则 passed=false。"""
# † JSON schema 由 with_structured_output(ReflectResult) 自动注入


async def reflector_node(state: AgentState) -> dict:
    """
    反思节点：评估 worker 结果质量
    
    返回:
    - needs_retry=False → 质量合格，继续到 synthesizer
    - needs_retry=True + feedback → 质量差，带反馈意见回到 worker 重做
    """
    if state.get("cancelled"):
        return {"needs_retry": False}

    worker_results = state.get("worker_results", [])
    if not worker_results:
        return {"needs_retry": False}

    # 拼接所有 worker 结果
    combined = "\n\n".join(
        f"[{r.get('worker_name', '?')}]: {r.get('result', '')}"
        for r in worker_results
    )

    # 已经重试过就不再重试（通过 state 里的计数判断）
    retry_count = state.get("retry_count", 0)
    if retry_count >= 1:
        log.info("已重试过 %d 次, 跳过反思", retry_count)
        return {"needs_retry": False}

    llm = get_llm(temperature=0.2)

    try:
        structured_llm = llm.with_structured_output(ReflectResult, method="json_mode")
        result = await structured_llm.ainvoke([
            SystemMessage(content=REFLECT_PROMPT.format(
                user_message=state["user_message"],
                agent_reply=combined[:3000],
            ))
        ])
        # result 已经是 ReflectResult 对象

        if result.passed:
            log.info("反思通过: overall=%.1f", result.overall)
            return {"needs_retry": False}
        else:
            log.info("反思未通过: overall=%.1f, feedback=%s", result.overall, result.feedback)
            return {
                "needs_retry": True,
                "reflection_feedback": result.feedback,
                "retry_count": retry_count + 1,
                "worker_results": [],
            }
    except Exception as e:
        log.warning("反思节点异常: %s, 默认通过", e)
        return {"needs_retry": False}
```

### 4.3 State 扩展

```python
# === app/graph/state.py 追加字段 ===

class AgentState(TypedDict):
    # ... 现有字段 ...

    # 反思循环
    needs_retry: bool               # 是否需要重试
    retry_count: int                # 已重试次数
    reflection_feedback: str        # 反思反馈（注入给 worker 改进）
```

### 4.4 修改 `app/graph/builder.py` — 加入反思边

```python
from app.graph.nodes.reflector import reflector_node

def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("search_worker", search_worker_node)
    graph.add_node("chat_worker", chat_worker_node)
    graph.add_node("analysis_worker", analysis_worker_node)
    graph.add_node("writing_worker", writing_worker_node)
    graph.add_node("reflector", reflector_node)       # ← 新增
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatcher_node)

    # Worker → Reflector (代替直接到 Synthesizer)
    graph.add_edge("search_worker", "reflector")       # ← 改这里
    graph.add_edge("chat_worker", "reflector")         # ← 改这里
    graph.add_edge("analysis_worker", "reflector")     # ← 改这里
    graph.add_edge("writing_worker", "reflector")      # ← 改这里

    # Reflector 条件边：通过 → synthesizer，未通过 → 重走 dispatcher
    graph.add_conditional_edges(
        "reflector",
        lambda state: "dispatcher" if state.get("needs_retry") else "synthesizer",
        {"dispatcher": "planner", "synthesizer": "synthesizer"},  
        # 注: 重试时回到 planner 让它重新分配，也可以直接回 dispatcher
    )

    graph.add_edge("synthesizer", END)
    return graph
```

### 4.5 Worker 使用反思反馈

各 worker 只需在构建 prompt 时检查 `reflection_feedback`：

```python
# === 以 search_worker_node 为例 ===

async def search_worker_node(state: AgentState) -> dict:
    # ... 前面不变 ...

    task_input = state["task_descriptions"].get("search", state["user_message"])

    # 如果有反思反馈，注入到任务描述中
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"

    # ... 后面不变 ...
```

### 4.6 学到了什么

| 技术点 | 说明 |
|--------|------|
| Self-Reflection | Agent 自我评估输出质量，是 2026 年构建可靠 Agent 的核心模式 |
| Conditional Loop | LangGraph 条件边实现"循环"，不是递归 |
| 有限重试 | `retry_count` 防止无限循环，实际场景中 1 次重试足够 |
| Feedback Injection | 反思意见注入 worker prompt，针对性改进 |

---

## 5. Agentic RAG 升级

> **核心价值**：RAG 不再是"每次都查"，Agent 自己判断何时检索、检索质量够不够  
> **2026 关键词**：Adaptive Retrieval, Self-RAG, Corrective RAG

### 5.1 架构设计

```
现有 RAG (每次都查)                    Agentic RAG (自适应)
──────────────────                     ─────────────────────
用户问题                               用户问题
  → Query Rewrite (必做)                 → 检索决策器 (新增)
  → 粗检索 (必做)                           ├── 不需要检索 → 直接回复
  → Reranker (必做)                         └── 需要检索 →
  → LLM 生成                                    Query Rewrite
                                                   → 粗检索 → Reranker
                                                   → 质量评估器 (新增)
                                                      ├── 质量够 → LLM 生成
                                                      └── 质量差 →
                                                           改写 Query 重试
                                                           或 调用 web_search 补充
```

### 5.2 新增文件：`app/services/adaptive_rag.py`

```python
"""
自适应 RAG 服务
实现 Adaptive Retrieval + Self-RAG + Corrective RAG

对应概念: Agentic RAG — 让 Agent 控制检索的时机、方式和质量
"""
import logging
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import get_llm
from app.services.query_rewrite import QueryRewriteService
from app.services.reranker import RerankerService
from app.clients.es_client import EsVectorStore, EsComponent
from app.tools.web_search import do_search

log = logging.getLogger(__name__)


# ─── 结构化输出 Model ───
class GradeResult(BaseModel):
    score: float = Field(description="质量评分 0-1")
    reason: str = Field(default="", description="简要理由")
    needs_web: bool = Field(default=False, description="是否需要联网搜索补充")


class RetrievalDecision(str, Enum):
    """检索决策"""
    NO_RETRIEVAL = "no_retrieval"       # 不需要检索，直接用 LLM 回答
    RETRIEVE = "retrieve"               # 需要检索
    WEB_SEARCH = "web_search"           # 需要联网搜索


@dataclass
class RetrievalResult:
    """检索结果 + 元数据"""
    documents: list[dict]
    quality_score: float               # 0-1 质量评分
    query_used: str                    # 实际使用的查询
    strategy: str                      # 使用的策略
    retry_count: int = 0              # 重试次数


# ─── Prompt 定义 ───

ROUTING_PROMPT = """判断以下用户问题是否需要检索外部信息才能回答。

【判断规则】
- 闲聊/打招呼/感谢 → no_retrieval
- 通用编程知识（LLM 自身知识能答好的）→ no_retrieval
- 需要查找特定文章/案例/数据 → retrieve
- 需要最新资讯/时效性信息 → web_search
- 不确定时 → retrieve（宁可多查）

用户问题: {query}
最近对话上下文: {context}

严格返回一个词: no_retrieval 或 retrieve 或 web_search"""

GRADING_PROMPT = """评估以下检索结果是否足以回答用户问题。

用户问题: {query}

检索结果:
{documents}

【评分标准】
- 检索到了直接相关的文章/代码/数据 → 高分 (0.7-1.0)
- 检索到了部分相关内容，需要补充 → 中分 (0.4-0.6)
- 没有检索到有用内容 → 低分 (0.0-0.3)

needs_web=true 表示需要联网搜索补充。"""
# † JSON schema 由 with_structured_output(GradeResult) 自动注入


class AdaptiveRAGService:
    """
    自适应 RAG 服务

    相比原有 search_worker 的改进:
    1. 检索路由：先判断需不需要检索
    2. 质量评估：检索后评估结果质量
    3. 自动补救：质量不够时改写 query 或联网补充
    4. 最多重试 1 次，避免死循环
    """

    def __init__(self):
        self._llm = get_llm(temperature=0.2)
        self._query_rewrite = QueryRewriteService()
        self._reranker = RerankerService()
        self._es_vector = EsVectorStore()
        self._es_text = EsComponent()

    # ─────────────── Step 1: 检索路由 ───────────────

    async def route(self, query: str, history: list[dict]) -> RetrievalDecision:
        """判断是否需要检索"""
        context = "\n".join(
            f"{m.get('role')}: {m.get('content', '')[:100]}"
            for m in history[-4:]
        ) if history else "无"

        try:
            resp = await self._llm.ainvoke([
                HumanMessage(content=ROUTING_PROMPT.format(query=query, context=context))
            ])
            decision = resp.content.strip().lower()
            if "no_retrieval" in decision:
                return RetrievalDecision.NO_RETRIEVAL
            elif "web_search" in decision:
                return RetrievalDecision.WEB_SEARCH
            else:
                return RetrievalDecision.RETRIEVE
        except Exception:
            return RetrievalDecision.RETRIEVE  # 降级：默认检索

    # ─────────────── Step 2: 执行检索 ───────────────

    async def retrieve(
        self, query: str, history: list[dict], max_retries: int = 1
    ) -> RetrievalResult:
        """
        完整的自适应检索流程

        流程: route → retrieve → grade → (retry or return)
        """
        # Step 1: 路由决策
        decision = await self.route(query, history)

        if decision == RetrievalDecision.NO_RETRIEVAL:
            return RetrievalResult(
                documents=[], quality_score=1.0,
                query_used=query, strategy="no_retrieval",
            )

        if decision == RetrievalDecision.WEB_SEARCH:
            web_results = await do_search(query, size=5)
            return RetrievalResult(
                documents=web_results, quality_score=0.7,
                query_used=query, strategy="web_search",
            )

        # Step 2: 标准 RAG 检索
        result = await self._do_retrieve(query, history)

        # Step 3: 质量评估
        score, needs_web = await self._grade(query, result.documents)
        result.quality_score = score

        # Step 4: 自动补救
        if score < 0.4 and result.retry_count < max_retries:
            log.info("检索质量低 (%.2f), 尝试改写 query 重试", score)

            # 改写 query
            rewrite = await self._query_rewrite.rewrite(
                f"上一次搜索不够好，请尝试不同的搜索角度: {query}", history
            )
            alt_query = rewrite["semantic_queries"][0] if rewrite["semantic_queries"] else query

            # 重试检索
            result = await self._do_retrieve(alt_query, history)
            result.retry_count += 1
            result.quality_score = (await self._grade(query, result.documents))[0]

        if needs_web and result.quality_score < 0.6:
            log.info("补充联网搜索")
            web_results = await do_search(query, size=3)
            result.documents.extend(web_results)
            result.strategy += "+web"

        return result

    async def _do_retrieve(self, query: str, history: list[dict]) -> RetrievalResult:
        """执行标准 RAG 检索（复用现有逻辑）"""
        rewrite = await self._query_rewrite.rewrite(query, history)

        # 多路召回
        doc_map = {}
        for sq in rewrite.get("semantic_queries", []):
            try:
                chunks = await self._es_vector.search(sq, top_k=5, threshold=0.5)
                for c in chunks:
                    key = f"{c.get('article_id')}_{c.get('chunk_index', 0)}"
                    if key not in doc_map:
                        doc_map[key] = c
            except Exception:
                pass

        for kw in rewrite.get("keywords", []):
            try:
                arts = await self._es_text.search(kw, page_size=5)
                for a in arts:
                    key = f"kw_{a.get('article_id')}"
                    if key not in doc_map:
                        doc_map[key] = a
            except Exception:
                pass

        candidates = list(doc_map.values())

        # Rerank
        if candidates:
            ranked = self._reranker.rerank(query, candidates)
        else:
            ranked = []

        return RetrievalResult(
            documents=ranked,
            quality_score=0.0,  # 待后续评分
            query_used=query,
            strategy="rag",
        )

    # ─────────────── Step 3: 质量评估 ───────────────

    async def _grade(self, query: str, documents: list[dict]) -> tuple[float, bool]:
        """
        评估检索结果质量

        返回: (score, needs_web)
        """
        if not documents:
            return 0.0, True

        doc_text = "\n".join(
            f"[{d.get('title', '无标题')}] {d.get('content', '')[:200]}"
            for d in documents[:5]
        )

        try:
            structured_llm = self._llm.with_structured_output(GradeResult, method="json_mode")
            result = await structured_llm.ainvoke([
                HumanMessage(content=GRADING_PROMPT.format(query=query, documents=doc_text))
            ])
            return result.score, result.needs_web
        except Exception:
            return 0.5, False  # 降级：中等分


# ─── 全局单例 ───
adaptive_rag = AdaptiveRAGService()
```

### 5.3 集成到 `search_worker.py`

```python
# === 改造 search_worker_node，使用 AdaptiveRAG 替代原有的固定检索流程 ===

from app.services.adaptive_rag import adaptive_rag

async def search_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("search", state["user_message"])
    history_messages = state["history_messages"]

    # ← 用 AdaptiveRAG 替代原来的 (query_rewrite → coarse_retrieval → rerank)
    rag_result = await adaptive_rag.retrieve(task_input, history_messages)

    # 旁路卡片（保持不变）
    article_cards = _build_cards_from_results(rag_result.documents)

    # 构建 RAG 上下文
    rag_context = build_rag_context(rag_result.documents)

    # 如果 route 判断不需要检索，简化 prompt
    if rag_result.strategy == "no_retrieval":
        reply = await run_tool_agent(
            system_prompt="你是一个智能助手，直接回答用户问题。",
            user_input=task_input,
            tools=None,
            max_rounds=0,
        )
    else:
        reply = await run_tool_agent(
            system_prompt=SEARCH_SYSTEM_PROMPT.format(
                current_date=datetime.now().strftime("%Y-%m-%d")
            ),
            user_input=(
                f"任务：{task_input}\n\n"
                f"RAG 参考资料（检索策略: {rag_result.strategy}, "
                f"质量评分: {rag_result.quality_score:.2f}）：\n{rag_context}"
            ),
            tools=AVAILABLE_TOOLS,
            max_rounds=2,
        )

    return {
        "worker_results": [{"worker_name": "search", "result": reply}],
        "article_cards": article_cards,
    }
```

### 5.4 学到了什么

| 技术点 | 说明 |
|--------|------|
| Adaptive Retrieval | Agent 先路由决策，不是每次都查，省 token 省时间 |
| Self-RAG | 检索后自评质量 → 不够就重试或联网补充 |
| Corrective RAG | 检索失败时自动改写 query + fallback 到 web search |
| Quality Grading | LLM-as-Judge 评估检索相关性，关键质量控制环节 |
| Retry Budget | max_retries=1 保证收敛，不会无限重试 |

---

## 实施路线建议

```
第 1 周: 可观测性（最简单，但价值立竿见影）
         ├── 装 langfuse
         ├── 给 run_tool_agent 加 callback
         └── 给 5 个 node 加 @trace_node

第 2-3 周: MCP 客户端
         ├── 加 mcp_client.py + tool_registry.py
         ├── 配一个 MCP Server 测试
         └── 改造 worker 用动态工具

第 4-5 周: Agentic RAG 升级
         ├── 加 adaptive_rag.py
         ├── 改造 search_worker
         └── 测试各种类型问题的检索决策

第 6-7 周: 反思循环
         ├── 加 reflector.py
         ├── 改造 builder.py 图结构
         └── 测试反思 + 重试路径

第 8-10 周: 长期记忆
         ├── 建表 + ES 索引
         ├── 加 memory.py
         ├── 集成到 chat_stream
         └── 测试跨会话记忆效果
```

---

## 新增依赖汇总

```txt
# requirements.txt 最终追加
langchain-mcp-adapters>=0.2,<1.0   # MCP 客户端（LangChain 官方适配器）
langfuse>=3.0,<4.0                 # 可观测性
```

## 新增文件汇总

```
app/
├── clients/
│   └── mcp_client.py              # MCP 客户端管理器
├── services/
│   ├── tool_registry.py           # 工具注册中心
│   ├── memory.py                  # 长期记忆服务
│   ├── observability.py           # 可观测性服务
│   └── adaptive_rag.py            # 自适应 RAG 服务
├── graph/
│   └── nodes/
│       └── reflector.py           # 反思节点
```

## 修改文件汇总

```
app/config.py                      # 追加 MCP 配置
app/main.py                        # lifespan 加 MCP, chat_stream 加记忆
app/graph/state.py                 # 追加 memory_context / needs_retry / retry_count
app/graph/builder.py               # 图结构加入 reflector 节点和条件边
app/graph/tool_executor.py         # 加入 LangFuse callback
app/graph/nodes/search_worker.py   # 使用 AdaptiveRAG + 动态工具
app/graph/nodes/*.py               # 各节点加 @trace_node 装饰器
```
