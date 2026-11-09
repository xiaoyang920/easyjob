![alt text](../../assets/python-agent/image.png)# 新增 Tool 设计方案

## 一、现有 Tool 清单

| Tool | 职责 | 所属 Worker |
|---|---|---|
| search_articles | ES 全文搜索平台文章 | SearchWorker |
| search_articles_by_knn | ES 向量语义搜索 | SearchWorker |
| web_search | 博查 API 联网搜索 | SearchWorker / AnalysisWorker |

## 二、新增 Tool

### 1. create_draft_article - 创建文章草稿

用户通过 AI 对话生成文章后，直接保存为平台草稿，不用手动复制粘贴。

```python
# python-agent/app/tools/article_tool.py 新增

@tool
async def create_draft_article(title: str, content: str, tags: str = "") -> str:
    """
    将 AI 生成的文章保存为平台草稿。
    
    Args:
        title: 文章标题
        content: 文章内容（Markdown 格式）
        tags: 文章标签，逗号分隔
    Returns:
        创建结果，包含草稿 ID
    """
    # 调用 Java 后端 API
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.JAVA_API_BASE}/api/article/draft",
            json={
                "title": title,
                "content": content,
                "tags": tags,
                "userId": ???,  # 需要从上下文获取 userId
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            return f"草稿创建成功，ID: {data.get('articleId')}"
        return f"创建失败: {resp.text}"
```

**难点**：需要在 Tool 调用时获取当前用户的 userId。

**解决方案**：在 AgentState 中新增 `user_id` 字段，main.py 初始化 state 时放入，Tool 从 state 中读取。

### 改动 1：AgentState 新增字段

```python
# python-agent/app/graph/state.py
class AgentState(TypedDict):
    user_id: int  # 新增：当前用户 ID，从请求参数传入
    # ... 其他字段不变
```

### 改动 2：main.py 初始化 state 时放入 user_id

```python
# main.py 的 chat() 和 chat_stream() 中
initial_state: AgentState = {
    "user_id": request.user_id,  # 新增
    "user_message": processed_message,
    "history_messages": context,
    # ... 其他字段不变
}
```

### 改动 3：Tool 不再需要 user_id 参数，从 state 获取

由于 LangChain 的 @tool 函数无法直接访问 AgentState，需要通过 Worker 在调用 Tool 前把 user_id 注入。

两种方式：

**方式 A：Worker 传参给 Tool（推荐）**

Worker 从 state 读 user_id，作为参数传给 run_tool_agent，Tool 保留 user_id 参数让 LLM 填：

```python
# Tool 定义：保留 user_id 参数，LLM 不需要知道具体值
# 在 Worker 的 System Prompt 中告诉 LLM："当前用户 ID 是 {user_id}"
system_prompt += f"\n\n【当前用户信息】用户ID: {state['user_id']}"
```

这样 LLM 看到 user_id 后会自动填入 Tool 调用参数。

**方式 B：全局 contextvars（更优雅）**

```python
# python-agent/app/utils/context.py
from contextvars import ContextVar
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=0)

# main.py 请求入口
current_user_id.set(request.user_id)

# Tool 内部
from app.utils.context import current_user_id
uid = current_user_id.get()
```

推荐方式 A，因为更显式，不依赖隐式的全局状态。

**适用场景**：
- "帮我写一篇 Spring Boot 入门教程并保存为草稿"
- WritingWorker 生成完内容后自动调用

---

### 2. get_user_articles - 获取用户文章列表

让 AI 能看到用户自己的文章，实现"帮我分析下我最近的文章"等场景。

```python
@tool
async def get_user_articles(user_id: int, page: int = 1, page_size: int = 10) -> str:
    """
    获取指定用户的文章列表。
    
    Args:
        user_id: 用户 ID
        page: 页码
        page_size: 每页数量
    Returns:
        文章列表，包含标题、摘要、发布时间、浏览量等
    """
    rows = await db.fetch_all(
        """
        SELECT article_id, title, summary, create_time, view_count, like_count, collect_count
        FROM article_info
        WHERE user_id = :uid AND status = 1
        ORDER BY create_time DESC
        LIMIT :limit OFFSET :offset
        """,
        {"uid": user_id, "limit": page_size, "offset": (page - 1) * page_size},
    )
    if not rows:
        return "该用户暂无已发布文章"
    
    articles = []
    for r in rows:
        row = dict(r._mapping)
        articles.append(
            f"- [{row['title']}] 浏览:{row['view_count']} 点赞:{row['like_count']} "
            f"收藏:{row['collect_count']} 发布于:{row['create_time']}"
        )
    return "\n".join(articles)
```

**适用场景**：
- "帮我看看我最近写的文章"
- "我哪篇文章浏览量最高"
- "帮我分析下我的文章数据"

---

### 3. get_trending_topics - 获取热门话题

让 AI 了解平台当前的热门内容，帮用户发现写作灵感。

```python
@tool
async def get_trending_topics(limit: int = 10) -> str:
    """
    获取平台当前热门标签和话题。
    
    Args:
        limit: 返回数量
    Returns:
        热门标签列表，包含标签名和文章数量
    """
    rows = await db.fetch_all(
        """
        SELECT t.tag_name, COUNT(r.article_id) as article_count
        FROM article_tag t
        JOIN article_tag_relation r ON t.tag_id = r.tag_id
        JOIN article_info a ON r.article_id = a.article_id AND a.status = 1
        GROUP BY t.tag_id, t.tag_name
        ORDER BY article_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    if not rows:
        return "暂无热门话题数据"
    
    topics = []
    for r in rows:
        row = dict(r._mapping)
        topics.append(f"- {row['tag_name']}（{row['article_count']} 篇文章）")
    return "当前平台热门话题：\n" + "\n".join(topics)
```

**适用场景**：
- "最近什么技术话题比较火"
- "帮我推荐一个写作方向"
- AnalysisWorker 分析平台趋势时使用

---

### 4. get_article_comments - 获取文章评论

让 AI 能看到文章的评论反馈，帮用户了解读者意见。

```python
@tool
async def get_article_comments(article_id: int, limit: int = 20) -> str:
    """
    获取指定文章的评论列表。
    
    Args:
        article_id: 文章 ID
        limit: 返回数量
    Returns:
        评论列表，包含评论内容、评论者、时间
    """
    rows = await db.fetch_all(
        """
        SELECT c.content, u.nick_name, c.create_time
        FROM article_comment c
        JOIN user_info u ON c.user_id = u.user_id
        WHERE c.article_id = :aid
        ORDER BY c.create_time DESC
        LIMIT :limit
        """,
        {"aid": article_id, "limit": limit},
    )
    if not rows:
        return "该文章暂无评论"
    
    comments = []
    for r in rows:
        row = dict(r._mapping)
        comments.append(f"- {row['nick_name']}：{row['content']}（{row['create_time']}）")
    return "\n".join(comments)
```

**适用场景**：
- "帮我看看这篇文章的评论反馈"
- "读者对我的文章有什么建议"

---

## 三、注册到 ToolRegistry

```python
# python-agent/app/services/tool_registry.py

from app.tools.article_tool import (
    search_articles, search_articles_by_knn,
    get_user_articles, get_trending_topics, get_article_comments,
)
from app.tools.web_search import web_search

class ToolRegistry:
    def __init__(self):
        self._local_tools: dict[str, BaseTool] = {
            "search_articles": search_articles,
            "search_articles_by_knn": search_articles_by_knn,
            "web_search": web_search,
            # 新增
            "get_user_articles": get_user_articles,
            "get_trending_topics": get_trending_topics,
            "get_article_comments": get_article_comments,
        }
```

## 四、Planner Prompt 更新

Planner 的 System Prompt 中更新可用工具描述，让 Planner 知道新 Tool 的存在：

```
【可用的Worker】
- search: 搜索专家，负责检索平台文章、联网搜索实时信息
- analysis: 分析专家，负责数据分析、对比分析、趋势分析、用户文章数据分析
- writing: 写作专家，负责文章撰写、内容创作、文案优化、保存草稿
- chat: 聊天专家，负责日常对话、简单问答、闲聊
```

## 五、优先级

| Tool | 复杂度 | 实用性 | 建议 |
|---|---|---|---|
| get_trending_topics | 低（纯 SQL） | 高 | 第一个做 |
| get_user_articles | 低（纯 SQL） | 高 | 第二个做 |
| get_article_comments | 低（纯 SQL） | 中 | 第三个做 |
| create_draft_article | 中（需要鉴权） | 高 | 第四个做（需要解决 userId 传递） |

前三个都是纯数据库查询，不需要鉴权，直接查 MySQL 就行，半小时能搞定。
