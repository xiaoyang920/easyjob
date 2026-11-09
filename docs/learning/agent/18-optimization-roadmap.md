# 项目优化与扩展路线图

## 一、未完成项（立即修复）

### 1.1 Planner 降级分支缺少 required_skills

**文件**：`python-agent/app/graph/nodes/planner.py`

**问题**：`except` 块返回的 dict 没有 `required_skills`，state 里会缺这个 key。

**修复**：
```python
except Exception as e:
    log.warning("Planner 解析失败，降级到 chat: %s", e)
    return {
        "active_workers": ["chat"],
        "task_descriptions": {"chat": state["user_message"]},
        "required_skills": [],  # 补上
    }
```

### 1.2 非流式 chat() 接口缺少 user_id

**文件**：`python-agent/app/main.py`

**问题**：`chat_stream` 里有 `"user_id": request.user_id`，但 `chat()` 接口的 `initial_state` 没传。

**修复**：
```python
initial_state: AgentState = {
    "user_id": request.user_id,  # 补上
    "user_message": processed_message,
    ...
}
```

### 1.3 创建 Skill 示例文件

**目录**：`python-agent/app/skills/definitions/`

需要创建目录和至少 2 个示例 Skill md 文件（spring_boot.md、interview_prep.md），否则 SkillRegistry 启动时扫描不到任何 Skill。

### 1.4 实现 create_draft_article Tool

**文件**：`python-agent/app/tools/article_tool.py`

设计文档已有（`docs/agent/tools/new-tools-design.md`），需要：
- 实现 Tool 函数，调用 Java 后端 API
- Worker 的 System Prompt 注入 `user_id`（方式 A）
- 注册到 ToolRegistry

### 1.5 清理 CostTracker 死代码

**文件**：`python-agent/app/services/observability.py`

删除 `CostTracker` 类，没有任何地方调用。

---

## 二、Agent 侧优化

### 2.1 上下文缓存优化（Redis 同步更新）

**目标**：减少 `get_context_for_llm` 每次都查 MySQL 的开销。

**方案**：
- `add_message` 写 MySQL 的同时，把新消息追加到 Redis 缓存
- `get_context_for_llm` 优先从 Redis 读，没有才回 MySQL
- `_maybe_compress` 压缩摘要后清缓存，下次读时从 MySQL 重建

**缓存 key**：`py_ctx:{conversation_id}`，TTL 2 小时

**改动文件**：`python-agent/app/services/conversation.py`

```python
# get_context_for_llm 加缓存
async def get_context_for_llm(self, conversation_id: int) -> list[dict]:
    # 1. 先查 Redis
    cached = await self._redis.get(self._context_cache_key(conversation_id))
    if cached:
        return json.loads(cached)
    
    # 2. Redis 没有，查 MySQL（原有逻辑）
    context = ...  # 原有的 MySQL 查询逻辑
    
    # 3. 写回 Redis
    await self._redis.set(
        self._context_cache_key(conversation_id),
        json.dumps(context, ensure_ascii=False, default=str),
        ex=CACHE_TTL,
    )
    return context

# add_message 末尾追加更新缓存
async def add_message(self, ...):
    ...  # 原有逻辑
    
    # 同步更新 LLM 上下文缓存（追加新消息）
    ctx_cached = await self._redis.get(self._context_cache_key(conversation_id))
    if ctx_cached:
        ctx_list = json.loads(ctx_cached)
        ctx_list.append({"role": role, "content": content})
        await self._redis.set(
            self._context_cache_key(conversation_id),
            json.dumps(ctx_list, ensure_ascii=False, default=str),
            ex=CACHE_TTL,
        )

# _maybe_compress 末尾清缓存
async def _maybe_compress(self, conversation_id: int):
    ...  # 原有逻辑
    # 压缩后清缓存，下次读时重建
    await self._redis.delete(self._context_cache_key(conversation_id))

def _context_cache_key(self, conversation_id: int) -> str:
    return f"py_ctx:{conversation_id}"
```

**效果**：平时都走 Redis，只有压缩时（每 30 条一次）才回 MySQL。

### 2.2 Worker 超时控制

**目标**：防止单个 Worker（如 Rerank API 超时）拖住整个流程。

**方案**：在每个 Worker 的核心调用外包一层 `asyncio.wait_for`。

**改动文件**：`python-agent/app/graph/tool_executor.py`

```python
import asyncio

async def run_tool_agent(
    system_prompt: str,
    user_input: str,
    tools: list[BaseTool] | None = None,
    max_rounds: int = 2,
    history_messages: list[BaseMessage] | None = None,
    timeout: float = 60.0,  # 新增：总超时时间
) -> str:
    try:
        return await asyncio.wait_for(
            _run_tool_agent_inner(system_prompt, user_input, tools, max_rounds, history_messages),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        log.warning("Tool Agent 超时 (%.0fs)，返回降级结果", timeout)
        return "抱歉，处理超时，请稍后重试。"
```

### 2.3 Planner 结果缓存

**目标**：相似问题短时间内不重复调 LLM 规划。

**方案**：
- 对用户消息做 hash，作为缓存 key
- 缓存 Planner 的输出（active_workers + task_descriptions + required_skills）
- TTL 5 分钟，同一个会话内相似问题直接复用

**改动文件**：`python-agent/app/graph/nodes/planner.py`

```python
import hashlib

def _plan_cache_key(user_message: str) -> str:
    h = hashlib.md5(user_message.encode()).hexdigest()[:16]
    return f"py_plan:{h}"

@trace_node("planner")
async def planner_node(state: AgentState) -> dict:
    # 检查缓存
    cache_key = _plan_cache_key(state["user_message"])
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # 原有 LLM 调用逻辑...
    result = {...}
    
    # 写缓存
    await redis_client.set(cache_key, json.dumps(result), ex=300)
    return result
```

**注意**：需要引入 RedisClient，或者通过 state 传递。

### 2.4 Tool 调用结果缓存

**目标**：同一个搜索查询短时间内不重复调 ES/API。

**方案**：在 `run_tool_agent` 的 Tool 执行环节加缓存层。

**改动文件**：`python-agent/app/graph/tool_executor.py`

```python
TOOL_CACHE_TTL = 120  # 2 分钟

async def _execute_tool_with_cache(fn, args, redis_client):
    cache_key = f"py_tool:{fn.name}:{hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]}"
    cached = await redis_client.get(cache_key)
    if cached:
        return cached
    result = await fn.invoke(args)
    result = _truncate_result(result)
    await redis_client.set(cache_key, result, ex=TOOL_CACHE_TTL)
    return result
```

---

## 三、博客侧扩展

### 3.1 文章推荐系统

**目标**：基于用户画像 + 行为数据做个性化推荐。

#### 现有数据基础

| 数据源 | 表 | 已有字段 | 说明 |
|--------|-----|----------|------|
| 用户画像 | user_profile | tech_stack, interests, experience | Agent 聊天自动提取 |
| 用户行为 | user_action | article_id, action_type, user_id | 点赞(2)/收藏(3)/投币(4)/分享(5) |
| 文章标签 | article_tag_relation | article_id, tag_id | 文章-标签关联 |
| 文章信息 | article_info | view_count, like_count, create_time | 热度数据 |

**缺少的数据**：浏览记录（用户看了哪些文章、停留多久）。

#### 第一步：新增浏览记录

**新增 action_type = 7（文章浏览）**：

```java
// ActionTypeEnum 新增
ARTICLE_VIEW(7, "文章浏览");
```

**记录位置**：在现有的 `GET /api/article/detail/{articleId}` 接口里记录浏览行为（用户一打开就记录），不是在 view_count 接口里（那个是 15 秒延迟加浏览量）。

两者区别：
- **浏览记录**（user_action）→ 详情页接口，立即记录，给推荐系统用
- **浏览量**（view_count）→ view 接口，15 秒延迟，防刷，给展示用

**存储方案**：直接用现有的 `user_action` 表，新增 `action_type = 7`（ARTICLE_VIEW），不用单开表。

**改动 1：ActionTypeEnum 新增浏览类型**

```java
// ActionTypeEnum.java
ARTICLE_VIEW(7, "文章浏览");
```

**改动 2：详情页接口里记录浏览行为**

在 `ArticleServiceImpl.getArticleById()` 方法末尾加浏览记录逻辑：

```java
// ArticleServiceImpl.getArticleById() 末尾新增
Long userId = UserContext.getUserId();
if (userId != null) {
    // Redis 去重：同一用户同一文章 24 小时内只记录一次
    String viewKey = RedisConstants.REDIS_KEY_ARTICLE_VIEW + userId + ":" + articleId;
    if (redisComponent.setIfAbsent(viewKey, "1", 24, TimeUnit.HOURS)) {
        // 写 user_action 表
        UserAction action = new UserAction();
        action.setUserId(userId);
        action.setArticleId(articleId);
        action.setArticleUserId(article.getUserId());
        action.setActionType(ActionTypeEnum.ARTICLE_VIEW.getCode());
        action.setActionCount(1);
        action.setActionTime(LocalDateTime.now());
        userActionMapper.insert(action);
    } else {
        // 24 小时内重复浏览，只更新时间（推荐系统用最近浏览时间排序）
        userActionMapper.updateViewTime(userId, articleId, LocalDateTime.now());
    }
}
```

**注意**：详情页接口 `/api/article/detail/**` 在拦截器中被排除了（未登录也能看文章），所以 `UserContext.getUserId()` 可能为 null，需要判空。已登录用户才记录浏览行为。

**改动 3：view_count 接口简化**

view_count 接口（`POST /{articleId}/view`）已走全局拦截器，删除手动认证逻辑，只负责加浏览量：

```java
@PostMapping("/{articleId}/view")
public ResponseVO<?> increaseViewCount(@PathVariable Long articleId) {
    articleService.increaseViewCount(articleId);
    return ResponseVO.success("浏览数增加成功");
}
```

#### 第二步：构建用户偏好

**用户-标签偏好分数计算**：

```
偏好分 = Σ(行为权重 × 标签关联)

行为权重：
- 浏览: 1 分
- 点赞: 3 分
- 收藏: 5 分
- 投币: 8 分
- 分享: 4 分
```

**定时任务**（每天凌晨跑一次）：

```sql
-- 计算每个用户对每个标签的偏好分
SELECT 
    ua.user_id,
    atr.tag_id,
    SUM(CASE ua.action_type
        WHEN 7 THEN 1   -- 浏览
        WHEN 2 THEN 3   -- 点赞
        WHEN 3 THEN 5   -- 收藏
        WHEN 4 THEN 8   -- 投币
        WHEN 5 THEN 4   -- 分享
        ELSE 0
    END) AS preference_score
FROM user_action ua
JOIN article_tag_relation atr ON ua.article_id = atr.article_id
WHERE ua.action_time > DATE_SUB(NOW(), INTERVAL 30 DAY)  -- 只看最近 30 天
GROUP BY ua.user_id, atr.tag_id
ORDER BY preference_score DESC;
```

**存储**：结果写入 `user_tag_preference` 表或 Redis Hash。

```sql
CREATE TABLE user_tag_preference (
    user_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    score FLOAT NOT NULL DEFAULT 0,
    update_time DATETIME NOT NULL,
    PRIMARY KEY (user_id, tag_id),
    INDEX idx_user_score (user_id, score DESC)
);
```

#### 第三步：推荐接口

**`GET /api/articles/recommend?limit=20`**

```
推荐流程：
1. 从 user_tag_preference 取用户 top10 偏好标签
2. 从这些标签关联的文章中，排除已浏览的
3. 按 (偏好分 × 0.5 + 热度分 × 0.3 + 时效分 × 0.2) 综合排序
4. 返回 top20
```

**热度分**：`(like_count * 2 + collect_count * 3 + view_count) / 时间衰减`

**时效分**：`1 / (1 + 距今天数 * 0.1)`，越新越高

**冷启动**：新用户没有偏好数据时：
- 优先用 user_profile 的 tech_stack/interests 匹配标签
- 都没有就返回全站热门文章

#### 第四步：与 Agent 联动

用户画像已经有了（Agent 聊天自动提取），推荐系统可以直接用：

```python
# Agent 提取的画像
tech_stack: ["Java", "Spring Boot", "Redis"]
interests: ["后端开发", "分布式系统"]

# 映射到标签 → 作为冷启动偏好
```

后续还可以让 Agent 主动推荐："根据你最近关注的 Redis 话题，推荐几篇相关文章给你看看？"

#### 改动文件清单

| 文件 | 改动 |
|------|------|
| `ActionTypeEnum.java` | 新增 ARTICLE_VIEW(7) |
| `ArticleController.java` | 新增 `/view/{articleId}` 接口 |
| `ArticleServiceImpl.java` | 新增 `recordView()` 方法 + Redis 去重 |
| 新增 `RecommendService.java` | 推荐核心逻辑 |
| 新增 `RecommendController.java` | `/api/articles/recommend` 接口 |
| 新增 `user_tag_preference` 表 | 用户-标签偏好存储 |
| 新增定时任务 | 每天计算偏好分 |
| 前端 `ArticleDetail.vue` | 打开文章时调浏览记录接口 |
| 前端 `Home.vue` | 新增"推荐"Tab |

### 3.2 消息通知系统

**目标**：评论、点赞、关注的实时通知。

**方案**：
- 后端：用户操作时写入 `notification` 表 + 发 RabbitMQ 消息
- 实时推送：WebSocket 或 SSE 推送给在线用户
- 离线用户：下次登录时拉取未读通知

**数据表设计**：
```sql
CREATE TABLE notification (
    notification_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,          -- 接收者
    sender_id BIGINT NOT NULL,        -- 触发者
    type TINYINT NOT NULL,            -- 1评论 2点赞 3关注 4系统
    target_id BIGINT,                 -- 目标ID（文章/评论）
    content VARCHAR(200),             -- 通知内容
    is_read TINYINT DEFAULT 0,        -- 0未读 1已读
    create_time DATETIME NOT NULL,
    INDEX idx_user_read (user_id, is_read)
);
```

**改动文件**：
- 新增 `NotificationService`、`NotificationController`
- `ArticleCommentServiceImpl.create()` 里发通知
- `UserActionServiceImpl` 点赞/关注时发通知
- 前端增加通知铃铛组件

### 3.3 文章标签自动生成

**目标**：发文章时用 LLM 自动提取标签，减少用户手动选择。

**方案**：
- 用户发布文章时，把标题 + 正文前 500 字发给 LLM
- LLM 返回 3-5 个推荐标签
- 前端展示推荐标签，用户可以修改后确认

**实现**：
```python
@tool
async def auto_tag_article(title: str, content: str) -> str:
    """根据文章内容自动生成标签推荐"""
    llm = get_llm(temperature=0.3)
    prompt = f"""根据以下文章内容，推荐 3-5 个最合适的技术标签。
    只返回标签名，逗号分隔。
    
    标题：{title}
    内容：{content[:500]}"""
    resp = await llm.ainvoke(prompt)
    return resp.content
```

也可以在 Java 端实现，发布文章时异步调用 Python Agent 的标签生成接口。

---

## 四、优先级排序

| 序号 | 任务 | 复杂度 | 优先级 | 预估时间 |
|------|------|--------|--------|----------|
| 1.1 | Planner 降级补 required_skills | 低 | P0 | 5 分钟 |
| 1.2 | chat() 补 user_id | 低 | P0 | 5 分钟 |
| 1.5 | 清理 CostTracker | 低 | P0 | 5 分钟 |
| 1.3 | 创建 Skill 示例文件 | 低 | P1 | 30 分钟 |
| 2.1 | 上下文 Redis 缓存优化 | 中 | P1 | 1 小时 |
| 2.2 | Worker 超时控制 | 低 | P1 | 30 分钟 |
| 1.4 | create_draft_article Tool | 中 | P2 | 2 小时 |
| 3.3 | 文章标签自动生成 | 低 | P2 | 1 小时 |
| 2.3 | Planner 结果缓存 | 中 | P2 | 1 小时 |
| 2.4 | Tool 调用结果缓存 | 中 | P2 | 1 小时 |
| 3.1 | 文章推荐系统 | 高 | P3 | 1-2 天 |
| 3.2 | 消息通知系统 | 高 | P3 | 1-2 天 |
