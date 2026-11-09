# 会话管理 + MySQL 持久化 + Human-in-the-Loop 方案

> Python Agent 全权管理 AI 会话，Java 端只做透传。Redis Checkpointer 负责图执行断点续传，ConversationService 负责业务会话的 CRUD、MySQL 持久化、**滚动摘要压缩**和 **Token 计数**。

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  Java 端 (AgentController)                                   │
│  只透传 user_id + conversation_id + message                   │
│  调 Python Agent 的 /chat 接口                                │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTP
┌────────────────────────────▼─────────────────────────────────┐
│  Python Agent (FastAPI)                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ConversationService (你的业务层)                          │ │
│  │  ├── 会话 CRUD (创建/列表/删除)                           │ │
│  │  ├── 消息存取 (MySQL + Redis 缓存)                       │ │
│  │  ├── 滚动摘要 (超出窗口的旧消息 → LLM 压缩成摘要)         │ │
│  │  ├── Token 计数 (每条消息入库时计算 token，预算控制)       │ │
│  │  └── MySQL: ai_conversation / ai_message 表              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Redis Checkpointer (LangGraph 内置)                      │ │
│  │  ├── 图节点间的 state 快照                                │ │
│  │  ├── interrupt() 暂停点持久化                             │ │
│  │  └── Command(resume=) 恢复执行                           │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘

Redis Key 空间隔离:
  py_conv:{id}:*           ← ConversationService 的缓存
  checkpoint:{thread_id}:* ← LangGraph Checkpointer 自动管理
```

### 核心原则：各管各的

| 关注点 | 谁负责 | 存储 |
|--------|--------|------|
| 聊天记录（用户看到的） | ConversationService | MySQL + Redis 缓存 |
| 图执行快照（interrupt/resume） | Checkpointer | Redis（LangGraph 自动管理） |
| 会话列表、标题、状态 | ConversationService | MySQL |
| 上下文管理（摘要 + 近期窗口） | ConversationService | 摘要存 MySQL，近期走 Redis |
| Token 计数与预算控制 | ConversationService + token_utils | 每条消息的 token_count 存 MySQL |

---

## 二、MySQL 表结构

沿用 Java 端已有的表，Python 直接连同一个 MySQL 库。

### ai_conversation 表

```sql
CREATE TABLE ai_conversation (
    conversation_id BIGINT       PRIMARY KEY COMMENT '会话ID（雪花ID）',
    user_id         BIGINT       NOT NULL    COMMENT '用户ID',
    title           VARCHAR(200) DEFAULT NULL COMMENT '会话标题（取首条消息前50字）',
    summary         TEXT         DEFAULT NULL COMMENT '滚动摘要（LLM压缩的早期对话精华）',
    summary_tokens  INT          DEFAULT 0   COMMENT '当前摘要的 token 数',
    summary_upto_msg_id BIGINT   DEFAULT NULL COMMENT '摘要已覆盖到的最后一条消息ID',
    message_count   INT          DEFAULT 0   COMMENT '消息数量',
    total_tokens    INT          DEFAULT 0   COMMENT '累计消耗 token 数（所有消息之和）',
    status          TINYINT      DEFAULT 1   COMMENT '1-正常 0-已删除',
    create_time     DATETIME     NOT NULL,
    update_time     DATETIME     NOT NULL,
    INDEX idx_user_update (user_id, status, update_time DESC)
) COMMENT 'AI会话表';
```

> **新增字段解析**：
> - `summary`：LLM 压缩生成的摘要，存早期对话的精华。触发压缩时，把旧消息一次性总结存进来。
> - `summary_tokens`：当前摘要占多少 token，用于预算控制（避免摘要本身膨胀到超限）。
> - `summary_upto_msg_id`：摘要覆盖到的最后一条消息 ID。读上下文时用 `WHERE message_id > summary_upto_msg_id` 只读未被总结的消息，也用于判断是否需要再次压缩。
> - `total_tokens`：整个会话累计消耗的 token 数，可用于用量统计、配额限制。

### ai_message 表

```sql
CREATE TABLE ai_message (
    message_id      BIGINT       PRIMARY KEY COMMENT '消息ID（雪花ID）',
    conversation_id BIGINT       NOT NULL    COMMENT '所属会话ID',
    role            VARCHAR(20)  NOT NULL    COMMENT 'user/assistant/system',
    content         TEXT                     COMMENT '消息内容',
    token_count     INT          DEFAULT 0   COMMENT '本条消息的 token 数',
    tool_calls      TEXT         DEFAULT NULL COMMENT '工具调用记录(JSON)',
    image_paths     JSON         DEFAULT NULL COMMENT '图片路径列表',
    article_cards   JSON         DEFAULT NULL COMMENT '文章卡片数据',
    create_time     DATETIME     NOT NULL,
    INDEX idx_conv_time (conversation_id, create_time ASC)
) COMMENT 'AI消息表';
```

> **解析**：`token_count` 在消息入库时就计算好存进去，后续统计和预算控制直接读数据库，不用每次重新算。

如果是在已有库上添加字段：

```sql
ALTER TABLE ai_conversation ADD COLUMN summary TEXT DEFAULT NULL COMMENT '滚动摘要（LLM压缩的早期对话精华）';
ALTER TABLE ai_conversation ADD COLUMN summary_tokens INT DEFAULT 0 COMMENT '当前摘要的token数';
ALTER TABLE ai_conversation ADD COLUMN summary_upto_msg_id BIGINT DEFAULT NULL COMMENT '摘要覆盖到的最后一条消息ID';
ALTER TABLE ai_conversation ADD COLUMN total_tokens INT DEFAULT 0 COMMENT '累计消耗token数';
```

> **解析**：Python 端和 Java 端共用同一套表。Java 用 MyBatis-Plus 的雪花算法自动生成 ID，Python 端也用 snowflake 库生成，保证 ID 不冲突。

---

## 三、依赖安装

在 `requirements.txt` 追加：

```
# MySQL 异步驱动
aiomysql>=0.2,<1.0
# 异步 ORM（轻量级，比 SQLAlchemy 更简洁）
databases[mysql]>=0.9,<1.0
# 雪花ID
snowflake-id>=1.0,<2.0
# Token 计数（OpenAI 开源的分词器，DeepSeek 兼容 cl100k_base 编码）
tiktoken>=0.7,<1.0
```

> **为什么选 tiktoken？**
> - OpenAI 开源的 BPE 分词库，C 实现，速度极快（百万 token/秒级）
> - DeepSeek 的 tokenizer 和 OpenAI 的 `cl100k_base` 编码高度兼容，误差 <5%
> - 不需要加载模型权重，纯 CPU 运算，零额外依赖

> **为什么选 aiomysql + databases？**  
> - FastAPI 是异步框架，同步 MySQL 驱动会阻塞事件循环
> - `databases` 库提供简洁的异步 SQL 接口，不需要定义 ORM Model
> - 也可以用 SQLAlchemy 2.0 的 async 模式，但对于这种只做 CRUD 的场景偏重

---

## 四、配置 `app/config.py`

```python
class Settings:
    # ... 已有配置 ...
    
    # MySQL
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "easyjob")
    
    @property
    def mysql_url(self) -> str:
        """databases 库用的连接字符串"""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
            "?charset=utf8mb4"
        )
```

> **解析**：密码通过环境变量注入，不硬编码。`mysql_url` 用 property 延迟拼接，方便 `databases.Database()` 初始化。

---

## 五、MySQL 客户端 `app/clients/mysql_client.py`

```python
"""
MySQL 异步客户端
对应 Java: MyBatis-Plus 的 Mapper 层
"""
from databases import Database
from app.config import settings

db = Database(settings.mysql_url)


async def startup():
    """FastAPI 启动时调用"""
    await db.connect()


async def shutdown():
    """FastAPI 关闭时调用"""
    await db.disconnect()
```

> **解析**：`databases.Database` 内置连接池管理，不需要手动管连接。在 FastAPI 的 lifespan 里调用 `startup/shutdown`。

---

## 六、雪花 ID 生成器 `app/utils/snowflake.py`

```python
"""
雪花ID生成器
对应 Java: MyBatis-Plus 的 IdType.ASSIGN_ID

为什么不用自增ID？
- 分布式环境下自增ID会冲突
- Python 和 Java 同时写 ai_message 表，必须用全局唯一ID
- 雪花ID天然有序，适合做 MySQL 主键
"""
import time
import threading

class SnowflakeGenerator:
    def __init__(self, worker_id: int = 2):
        """
        worker_id: 0~31，和 Java 端区分开
        Java 默认 worker_id=1，Python 用 2，避免冲突
        """
        self._worker_id = worker_id & 0x1F  # 5 bit
        self._sequence = 0
        self._last_ts = -1
        self._lock = threading.Lock()
        self._epoch = 1609459200000  # 2021-01-01 00:00:00 UTC

    def next_id(self) -> int:
        with self._lock:
            ts = int(time.time() * 1000)
            if ts == self._last_ts:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    while ts <= self._last_ts:
                        ts = int(time.time() * 1000)
            else:
                self._sequence = 0
            self._last_ts = ts
            return ((ts - self._epoch) << 22) | (self._worker_id << 12) | self._sequence

snowflake = SnowflakeGenerator(worker_id=2)
```

> **解析**：Java 端 MyBatis-Plus 默认用 worker_id=1，Python 端设为 2，确保两端写同一张表时 ID 不冲突。

---

## 6.5、Token 计数工具 `app/utils/token_utils.py`

```python
"""
Token 计数工具
用于消息入库时计算 token、构建上下文时做预算控制

【为什么不用 len(text) / 4 估算？】
- 中文平均 1 字 ≈ 1~2 token，英文平均 1 词 ≈ 1.3 token
- 混合内容（中英 + 代码）误差可达 50%+
- tiktoken 用和 LLM 一致的 BPE 分词，偏差 <5%
"""
import tiktoken

# cl100k_base：GPT-4 / DeepSeek 系列通用编码
# 初始化一次，后续复用（线程安全）
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """
    计算文本的 token 数
    
    >>> count_tokens("你好世界")     → 4
    >>> count_tokens("Hello World")  → 2
    >>> count_tokens("")             → 0
    """
    if not text:
        return 0
    return len(_encoder.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """
    计算消息列表的总 token 数
    
    每条消息额外算 4 token 开销（role标记 + 分隔符），
    这是 OpenAI Chat API 的计费方式，DeepSeek 近似。
    """
    total = 0
    for msg in messages:
        total += 4  # role + 分隔符开销
        total += count_tokens(msg.get("content", ""))
    total += 2  # 尾部 assistant 起始标记
    return total


def truncate_to_token_budget(text: str, max_tokens: int) -> str:
    """
    将文本截断到不超过 max_tokens
    用于摘要超长时的兜底截断
    """
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _encoder.decode(tokens[:max_tokens])
```

> **解析要点**：
> - `_encoder` 是模块级单例，`tiktoken.get_encoding()` 首次调用会下载编码文件（~1MB），后续走本地缓存。
> - `count_messages_tokens` 里的 +4 / +2 开销是 Chat API 的标准格式开销（`<|im_start|>role\ncontent<|im_end|>`），不算会少估 5~10%。
> - `truncate_to_token_budget` 是安全兜底：万一 LLM 生成的摘要超限，直接按 token 边界截断，不会切断多字节字符。

---

## 七、ConversationService `app/services/conversation.py`

这是核心服务，完整替代 Java 端的 `AiConversationService`。相比简单滑动窗口，增加了**滚动摘要**和 **Token 计数**。

### 上下文管理策略图解

```
消息总量较少（未触发压缩）：直接全部作为上下文
  [msg1] [msg2] [msg3] ... [msg_N]  → 全部注入 LLM
  (summary_upto_msg_id = NULL)

未总结消息数达到 SUMMARY_TRIGGER(30)：总结前 20 条，保留最近 10 条
  [summary: msg1~msg20 的精华]     [msg21] [msg22] ... [msg30]
       ↑ LLM 一次性压缩                ↑ 保留的 KEEP_RECENT=10 条原文
       summary_upto_msg_id = msg20.id

下次读上下文：summary + WHERE message_id > msg20.id
  → 拿到 [summary] + [msg21 ~ msg30] 原文

继续聊到 msg50，未总结消息又达到 30 条（msg21~msg50）：
  总结 msg21~msg40，保留 msg41~msg50
  [summary: msg1~msg40 的精华]     [msg41] ... [msg50]
       ↑ 旧摘要 + msg21~msg40 → 新摘要
       summary_upto_msg_id = msg40.id
```

### 常量

```
SUMMARY_BUDGET   = 2000     ← 摘要最多 2000 token
SUMMARY_TRIGGER  = 30       ← 未总结消息数达到 30 时触发压缩
KEEP_RECENT      = 10       ← 压缩时保留最近 10 条不总结
```

> **解析**：
> - **KEEP_RECENT = 10**：压缩时保留最近 10 条原文不总结。这样压缩完 LLM 仍然能看到最近的完整对话细节，不会出现"刚总结完上下文只剩 summary + 0 条消息"的情况。
> - **SUMMARY_TRIGGER = 30**：每积累 30 条未总结消息就压缩一次，实际只总结前 20 条（30 - KEEP_RECENT），游标前移到第 20 条。
> - **成本控制**：每次给 LLM 的上下文是 summary（~2K）+ 未总结消息（10~30 条），比塞满 64K 省很多 token。

### 完整代码

```python
"""
会话管理服务
对应 Java: AiConversationService

【上下文管理策略】
- 总结重开：消息数达到阈值时，一次性总结所有旧消息，只保留 summary + 最近几轮
- Token 计数：每条消息入库时计算 token 数，用于统计和预算控制

【职责分工】
- 本服务：会话 CRUD、消息存取、摘要压缩、Token 计数、MySQL 持久化
- Checkpointer：图执行暂停/恢复（interrupt/resume），本服务不关心
"""
import json
import logging
from datetime import datetime

from app.clients.mysql_client import db
from app.clients.redis_client import RedisClient
from app.config import get_llm
from app.utils.snowflake import snowflake
from app.utils.token_utils import count_tokens, count_messages_tokens, truncate_to_token_budget

log = logging.getLogger(__name__)

# ─────────── 常量 ───────────
SUMMARY_BUDGET  = 2000  # 摘要最多占用的 token
SUMMARY_TRIGGER = 30    # 游标后未总结消息数达到此值时触发压缩
KEEP_RECENT     = 10    # 压缩时保留最近 10 条不总结（保持原文细节）
CACHE_TTL       = 7200  # Redis 缓存 2 小时

SUMMARY_PROMPT = """请将以下对话内容压缩成简洁的摘要。

【必须保留】
- 用户的核心需求、偏好、提到的关键名词（项目名、技术栈、人名等）
- 已经达成的结论和决策
- 重要的上下文背景信息

【不需要保留】
- 寒暄、客套话
- 重复的内容
- 过程中的试错和废弃方案

{old_summary_section}

【需要压缩的新对话】
{new_messages}

请输出压缩后的摘要（不超过500字）："""


class ConversationService:
    def __init__(self):
        self._redis = RedisClient()

    # ═══════════════════ 会话级操作 ═══════════════════

    async def create_conversation(self, user_id: int) -> int:
        """
        创建新会话，返回 conversation_id
        对应 Java: createConversation()
        """
        conv_id = snowflake.next_id()
        now = datetime.now()
        await db.execute(
            """
            INSERT INTO ai_conversation 
                (conversation_id, user_id, message_count, total_tokens, status, create_time, update_time)
            VALUES 
                (:conv_id, :user_id, 0, 0, 1, :now, :now)
            """,
            {"conv_id": conv_id, "user_id": user_id, "now": now},
        )
        return conv_id

    async def list_conversations(
        self, user_id: int, last_update_time: datetime | None = None,
        last_id: int | None = None, limit: int = 10
    ) -> list[dict]:
        """
        游标分页获取会话列表
        对应 Java: getUserConversationsWithCursor()
        """
        if last_update_time and last_id:
            rows = await db.fetch_all(
                """
                SELECT * FROM ai_conversation
                WHERE user_id = :uid AND status = 1
                  AND (update_time < :t OR (update_time = :t AND conversation_id < :lid))
                ORDER BY update_time DESC, conversation_id DESC
                LIMIT :lim
                """,
                {"uid": user_id, "t": last_update_time, "lid": last_id, "lim": limit},
            )
        else:
            rows = await db.fetch_all(
                """
                SELECT * FROM ai_conversation
                WHERE user_id = :uid AND status = 1
                ORDER BY update_time DESC
                LIMIT :lim
                """,
                {"uid": user_id, "lim": limit},
            )
        return [dict(r._mapping) for r in rows]

    async def delete_conversation(self, conversation_id: int):
        """
        删除会话（软删除 + 清 Redis）
        对应 Java: clearContext()
        """
        await db.execute(
            "UPDATE ai_conversation SET status = 0 WHERE conversation_id = :cid",
            {"cid": conversation_id},
        )
        await self._redis.delete(self._cache_key(conversation_id))

    # ═══════════════════ 上下文构建（核心） ═══════════════════

    async def get_context_for_llm(self, conversation_id: int) -> list[dict]:
        """
        构建注入给 LLM 的上下文消息列表
        
        【这是给图节点用的，替代原来的 get_history】
        
        返回格式：[摘要(system)] + [游标之后的所有消息(user/assistant)]
        
        【流程】
        1. 从 MySQL 读 summary + summary_upto_msg_id
        2. 若有摘要 → 放在最前面
        3. 读 message_id > summary_upto_msg_id 的所有消息（即未被总结的）
           若 summary_upto_msg_id 为 NULL → 从未压缩过，读全部消息
        4. 组装返回
        """
        context: list[dict] = []

        # 1. 读会话的 summary 和游标
        row = await db.fetch_one(
            "SELECT summary, summary_upto_msg_id FROM ai_conversation WHERE conversation_id = :cid",
            {"cid": conversation_id},
        )
        summary = row._mapping["summary"] if row else None
        cursor_id = row._mapping["summary_upto_msg_id"] if row else None

        if summary:
            context.append({
                "role": "system",
                "content": f"[之前的对话摘要]\n{summary}",
            })

        # 2. 读游标之后的所有消息（未被总结的部分）
        if cursor_id:
            rows = await db.fetch_all(
                """
                SELECT role, content FROM ai_message
                WHERE conversation_id = :cid AND message_id > :cursor
                ORDER BY create_time ASC
                """,
                {"cid": conversation_id, "cursor": cursor_id},
            )
        else:
            # 没有游标 → 从未压缩过，读全部消息
            rows = await db.fetch_all(
                """
                SELECT role, content FROM ai_message
                WHERE conversation_id = :cid
                ORDER BY create_time ASC
                """,
                {"cid": conversation_id},
            )

        for r in rows:
            context.append({"role": r._mapping["role"], "content": r._mapping["content"]})

        log.debug(
            "构建上下文: conv=%s, 有摘要=%s, 游标后消息=%d条",
            conversation_id, bool(summary), len(rows),
        )
        return context

    async def get_history(self, conversation_id: int) -> list[dict]:
        """
        获取会话全部消息（给前端展示用，不做 token 截断）
        
        对应 Java: getContext()
        
        【注意】这个方法返回所有消息，是给"查看历史"接口用的。
        给 LLM 的上下文用 get_context_for_llm()，会做摘要+预算控制。
        """
        cached = await self._redis.get(self._cache_key(conversation_id))
        if cached:
            return json.loads(cached)

        messages = await self._get_all_messages(conversation_id)
        result = [
            {
                "role": m["role"],
                "content": m["content"],
                "image_paths": m.get("image_paths"),
                "article_cards": m.get("article_cards"),
                "token_count": m.get("token_count", 0),
                "create_time": m.get("create_time"),
            }
            for m in messages
        ]
        await self._save_cache(conversation_id, result)
        return result

    # ═══════════════════ 消息写入 ═══════════════════

    async def add_message(
        self, conversation_id: int, role: str, content: str,
        image_paths: list[str] | None = None,
        article_cards: list[dict] | None = None,
    ):
        """
        添加一条消息：计算token → 写 MySQL → 更新统计 → 检查是否触发摘要 → 刷缓存
        
        对应 Java: addMessage()
        """
        msg_id = snowflake.next_id()
        now = datetime.now()
        token_count = count_tokens(content)

        # 1. 写 MySQL（带 token_count）
        await db.execute(
            """
            INSERT INTO ai_message
                (message_id, conversation_id, role, content, token_count, 
                 image_paths, article_cards, create_time)
            VALUES
                (:mid, :cid, :role, :content, :tc, :imgs, :cards, :now)
            """,
            {
                "mid": msg_id,
                "cid": conversation_id,
                "role": role,
                "content": content,
                "tc": token_count,
                "imgs": json.dumps(image_paths, ensure_ascii=False) if image_paths else None,
                "cards": json.dumps(article_cards, ensure_ascii=False) if article_cards else None,
                "now": now,
            },
        )

        # 2. 更新会话统计（message_count + total_tokens）
        await db.execute(
            """
            UPDATE ai_conversation 
            SET message_count = message_count + 1,
                total_tokens = total_tokens + :tc,
                update_time = :now
            WHERE conversation_id = :cid
            """,
            {"cid": conversation_id, "tc": token_count, "now": now},
        )

        # 3. 首条 user 消息设为标题
        if role == "user":
            row = await db.fetch_one(
                "SELECT title FROM ai_conversation WHERE conversation_id = :cid",
                {"cid": conversation_id},
            )
            if row and row._mapping["title"] is None:
                title = content[:50] + "..." if len(content) > 50 else content
                await db.execute(
                    "UPDATE ai_conversation SET title = :title WHERE conversation_id = :cid",
                    {"title": title, "cid": conversation_id},
                )

        # 4. 检查是否需要触发摘要压缩
        #    统计游标之后的未总结消息数，达到 SUMMARY_TRIGGER 才压缩
        row = await db.fetch_one(
            "SELECT summary_upto_msg_id FROM ai_conversation WHERE conversation_id = :cid",
            {"cid": conversation_id},
        )
        if row:
            cursor_id = row._mapping["summary_upto_msg_id"]
            if cursor_id:
                cnt_row = await db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM ai_message WHERE conversation_id = :cid AND message_id > :cursor",
                    {"cid": conversation_id, "cursor": cursor_id},
                )
            else:
                cnt_row = await db.fetch_one(
                    "SELECT COUNT(*) AS cnt FROM ai_message WHERE conversation_id = :cid",
                    {"cid": conversation_id},
                )
            unsummarized = cnt_row._mapping["cnt"] if cnt_row else 0
            if unsummarized >= SUMMARY_TRIGGER:
                await self._maybe_compress(conversation_id)

        # 5. 清 Redis 缓存（下次读会重建）
        await self._redis.delete(self._cache_key(conversation_id))

        log.debug("添加消息: conv=%s, role=%s, tokens=%d", conversation_id, role, token_count)

    # ═══════════════════ 摘要压缩 ═══════════════════

    async def _maybe_compress(self, conversation_id: int):
        """
        执行摘要压缩（游标方案）
        
        【调用前提】
        add_message 已判断游标后的未总结消息数 >= SUMMARY_TRIGGER
        
        【压缩策略】
        1. 读游标之后的所有未总结消息
        2. 保留最近 KEEP_RECENT 条不总结（保持原文细节）
        3. 旧摘要 + 前面的消息 → LLM 一次性生成新摘要
        4. 游标前移到最后一条被总结消息，不删原始消息
        """
        # 1. 读会话信息
        conv = await db.fetch_one(
            "SELECT summary, summary_upto_msg_id FROM ai_conversation WHERE conversation_id = :cid",
            {"cid": conversation_id},
        )
        if not conv:
            return
        old_summary = conv._mapping["summary"]
        cursor_id = conv._mapping["summary_upto_msg_id"]

        # 2. 读游标之后的所有未总结消息
        if cursor_id:
            rows = await db.fetch_all(
                """
                SELECT message_id, role, content FROM ai_message
                WHERE conversation_id = :cid AND message_id > :cursor
                ORDER BY create_time ASC
                """,
                {"cid": conversation_id, "cursor": cursor_id},
            )
        else:
            rows = await db.fetch_all(
                """
                SELECT message_id, role, content FROM ai_message
                WHERE conversation_id = :cid
                ORDER BY create_time ASC
                """,
                {"cid": conversation_id},
            )

        if not rows:
            return

        all_msgs = [dict(r._mapping) for r in rows]

        # 保留最近 KEEP_RECENT 条不总结，只总结前面的
        to_summarize = all_msgs[:-KEEP_RECENT] if len(all_msgs) > KEEP_RECENT else all_msgs
        if not to_summarize:
            return
        # 新游标 = 最后一条被总结消息的 message_id
        new_cursor_id = to_summarize[-1]["message_id"]

        # 3. 组装压缩 prompt
        new_messages_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in to_summarize
        )

        old_summary_section = ""
        if old_summary:
            old_summary_section = f"【已有摘要（在此基础上增量更新）】\n{old_summary}\n"

        prompt = SUMMARY_PROMPT.format(
            old_summary_section=old_summary_section,
            new_messages=new_messages_text,
        )

        # 4. LLM 生成摘要
        llm = get_llm(temperature=0)
        result = await llm.ainvoke(prompt)
        new_summary = result.content

        # 兜底：截断到预算内
        summary_tokens = count_tokens(new_summary)
        if summary_tokens > SUMMARY_BUDGET:
            new_summary = truncate_to_token_budget(new_summary, SUMMARY_BUDGET)
            summary_tokens = SUMMARY_BUDGET

        # 5. 写入 MySQL（摘要 + 游标一起更新）
        await db.execute(
            """
            UPDATE ai_conversation 
            SET summary = :s, summary_tokens = :st, summary_upto_msg_id = :cursor
            WHERE conversation_id = :cid
            """,
            {"s": new_summary, "st": summary_tokens, "cursor": new_cursor_id, "cid": conversation_id},
        )

        log.info(
            "摘要压缩完成: conv=%s, 总结了%d条, 保留最近%d条, 新游标=%s, 摘要=%d tokens",
            conversation_id, len(to_summarize), len(all_msgs) - len(to_summarize),
            new_cursor_id, summary_tokens,
        )

    # ═══════════════════ 私有方法 ═══════════════════

    def _cache_key(self, conversation_id: int) -> str:
        return f"py_conv:{conversation_id}"

    async def _save_cache(self, conversation_id: int, messages: list[dict]):
        await self._redis.set(
            self._cache_key(conversation_id),
            json.dumps(messages, ensure_ascii=False, default=str),
            ex=CACHE_TTL,
        )

    async def _get_all_messages(self, conversation_id: int) -> list[dict]:
        """从 MySQL 读取所有消息（按时间正序）—— 仅给前端 get_history 用"""
        rows = await db.fetch_all(
            """
            SELECT role, content, token_count, image_paths, article_cards, create_time
            FROM ai_message
            WHERE conversation_id = :cid
            ORDER BY create_time ASC
            """,
            {"cid": conversation_id},
        )
        return [
            {
                "role": r._mapping["role"],
                "content": r._mapping["content"],
                "token_count": r._mapping["token_count"] or 0,
                "image_paths": json.loads(r._mapping["image_paths"]) if r._mapping["image_paths"] else None,
                "article_cards": json.loads(r._mapping["article_cards"]) if r._mapping["article_cards"] else None,
                "create_time": str(r._mapping["create_time"]) if r._mapping["create_time"] else None,
            }
            for r in rows
        ]

```

### 和旧版（纯滑动窗口）的关键区别

| 对比项 | 旧版 `_truncate` | 新版 `get_context_for_llm` |
|--------|------------------|---------------------------|
| 截断依据 | 轮数（MAX_ROUNDS * 2 条） | `summary_upto_msg_id` 游标分界 |
| 旧消息处理 | 直接丢弃 | LLM 压缩成摘要，保留精华 |
| 第 50 轮问"之前说了啥" | 完全不知道 | 摘要里保留了要点 |
| LLM 额外调用 | 无 | 压缩时 1 次（低频，30+ 条消息才触发） |
| 上下文大小 | 可能很大 | 摘要 + 游标后的消息，精简高效 |
| MySQL 额外字段 | 无 | `summary`、`summary_tokens`、`summary_upto_msg_id`、`total_tokens`、每条消息 `token_count` |

> **解析**：
> - 旧版 `get_history` 保留用于前端展示全部消息（不截断）。
> - 新版 `get_context_for_llm` 才是给图节点用的，读 summary + 游标后的消息，轻量高效。
> - 不再需要 `_get_recent_messages`——直接用 `message_id > summary_upto_msg_id` 一条 SQL 搞定。
> - `add_message` 里每条消息入库时都计算 `token_count` 并存 MySQL，后续统计直接读库字段。

---

## 八、Graph Builder 调整 `app/graph/builder.py`

不需要大改，只确保 Checkpointer 正确注入：

```python
"""
builder.py — Checkpointer 仅用于图执行状态（interrupt/resume）
"""
from langgraph.graph import StateGraph, START, END, CompiledStateGraph
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from app.config import settings
from app.graph.state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.dispatcher import dispatcher_node
from app.graph.nodes.search_worker import search_worker_node
from app.graph.nodes.chat_worker import chat_worker_node
from app.graph.nodes.writing_worker import writing_worker_node
from app.graph.nodes.analysis_worker import analysis_worker_node
from app.graph.nodes.synthesizer import synthesizer_node


def _build_graph() -> StateGraph:
    """构建图结构（不含 checkpointer）"""
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("search_worker", search_worker_node)
    graph.add_node("chat_worker", chat_worker_node)
    graph.add_node("analysis_worker", analysis_worker_node)
    graph.add_node("writing_worker", writing_worker_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatcher_node)
    graph.add_edge("search_worker", "synthesizer")
    graph.add_edge("chat_worker", "synthesizer")
    graph.add_edge("analysis_worker", "synthesizer")
    graph.add_edge("writing_worker", "synthesizer")
    graph.add_edge("synthesizer", END)
    return graph


# -------- 全局单例 --------

_compiled_graph: CompiledStateGraph | None = None
_checkpointer: AsyncRedisSaver | None = None


async def get_graph() -> CompiledStateGraph:
    """
    获取带 Checkpointer 的编译图（单例，应用生命周期内只初始化一次）
    
    【为什么要单例？】
    - AsyncRedisSaver 内部维护连接池，不应每次请求重建
    - 编译图本身是无状态的，状态通过 config 的 thread_id 区分
    """
    global _compiled_graph, _checkpointer
    if _compiled_graph is None:
        redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
        _checkpointer = AsyncRedisSaver.from_conn_string(redis_url)
        await _checkpointer.asetup()
        _compiled_graph = _build_graph().compile(checkpointer=_checkpointer)
    return _compiled_graph
```

> **解析**：graph 和 checkpointer 都用模块级单例。每个请求通过 `config={"configurable": {"thread_id": ...}}` 区分不同会话的图执行上下文。

---

## 九、主入口 `app/main.py` 改造

```python
"""
FastAPI 入口 — AI 功能全部在此模块
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langgraph.types import Command

from app.graph.builder import get_graph
from app.graph.state import AgentState
from app.services.conversation import ConversationService
from app.clients import mysql_client


# ─────────── 生命周期 ───────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时连接 MySQL，关闭时断开"""
    await mysql_client.startup()
    yield
    await mysql_client.shutdown()

app = FastAPI(title="EasyJob Python Agent", lifespan=lifespan)
conversation_service = ConversationService()


# ─────────── 请求/响应模型 ───────────

class ChatRequest(BaseModel):
    user_id: int
    conversation_id: int | None = None
    message: str
    image_paths: list[str] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: str           # 字符串，前端 JS 大数不丢精度
    articles: list[dict] = Field(default_factory=list)

class ResumeRequest(BaseModel):
    """Human-in-the-loop 恢复请求"""
    user_id: int
    conversation_id: int
    action: str                     # 用户的决策，如 "approve" / "reject" / 自由文本


# ─────────── 接口 ───────────

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    非流式聊天（完整流程）
    
    【流程】
    1. 无 conversation_id → 创建新会话
    2. ConversationService 取历史并截断
    3. 组装 state，调图执行
    4. 保存 user + assistant 消息到 MySQL
    5. 返回结果
    
    【Checkpointer 在这里做了什么？】
    - 图内每个节点执行后自动保存快照到 Redis
    - 如果某个节点调了 interrupt()，图会暂停，本接口返回中断信息
    - 恢复时走 /chat/resume 接口
    """
    graph = await get_graph()

    # 1. 会话管理
    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)

    # 2. 先保存用户消息（在图执行之前，防止异常/暂停/中断导致消息丢失）
    await conversation_service.add_message(conv_id, "user", request.message)

    # 3. 构建上下文（摘要 + 近期窗口，按 token 预算控制）
    #    注意：放在 add_message 之后，这样刚保存的用户消息也能被纳入上下文
    context = await conversation_service.get_context_for_llm(conv_id)

    # 4. 组装 state
    initial_state: AgentState = {
        "user_message": request.message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }

    # 5. 执行图（thread_id 给 Checkpointer 做断点续传）
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    result = await graph.ainvoke(initial_state, config=config)

    # 6. 检查是否被 interrupt 暂停
    state = await graph.aget_state(config)
    if state.next:  # next 非空说明图还没执行完，被 interrupt 暂停了
        return ChatResponse(
            reply=json.dumps({
                "interrupted": True,
                "pending_node": list(state.next),
                "payload": state.tasks[0].interrupts[0].value if state.tasks else None,
            }, ensure_ascii=False),
            conversation_id=str(conv_id),
        )

    # 7. 正常完成 → 只保存 assistant 回复（user 消息已在步骤 2 保存）
    reply = result.get("final_reply", "抱歉，处理出错了")
    await conversation_service.add_message(conv_id, "assistant", reply)

    return ChatResponse(reply=reply, conversation_id=str(conv_id))


@app.post("/chat/resume", response_model=ChatResponse)
async def chat_resume(request: ResumeRequest):
    """
    Human-in-the-loop：恢复被 interrupt 暂停的图执行
    
    【什么时候走这个接口？】
    当 /chat 返回 interrupted=true 时，前端展示中断 payload（如草稿预览），
    用户做出决策后，前端调本接口传入 action。
    
    【内部流程】
    1. 用 Command(resume=action) 恢复图执行
    2. Checkpointer 自动从暂停点恢复，interrupt() 返回 action 的值
    3. 节点继续执行直到下一个 interrupt 或 END
    """
    graph = await get_graph()
    conv_id = request.conversation_id
    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}

    # 用 Command 恢复，resume 的值会成为 interrupt() 的返回值
    result = await graph.ainvoke(Command(resume=request.action), config=config)

    # 再次检查是否还有 interrupt
    state = await graph.aget_state(config)
    if state.next:
        return ChatResponse(
            reply=json.dumps({
                "interrupted": True,
                "pending_node": list(state.next),
                "payload": state.tasks[0].interrupts[0].value if state.tasks else None,
            }, ensure_ascii=False),
            conversation_id=str(conv_id),
        )

    reply = result.get("final_reply", "抱歉，处理出错了")
    await conversation_service.add_message(conv_id, "assistant", reply)

    return ChatResponse(reply=reply, conversation_id=str(conv_id))


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    SSE 流式聊天
    
    【和非流式的区别】
    - 图执行逻辑相同
    - 用 astream_events 逐 token 推送
    - 流结束后再保存消息
    
    【注意】流式模式下 interrupt 会以 SSE event 的形式通知前端
    """
    graph = await get_graph()

    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)

    # 先保存用户消息（在图执行之前，防止异常/暂停导致消息丢失）
    await conversation_service.add_message(conv_id, "user", request.message)

    # 构建上下文（放在 add_message 之后，用户消息也能纳入上下文）
    context = await conversation_service.get_context_for_llm(conv_id)

    initial_state: AgentState = {
        "user_message": request.message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }

    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    full_reply: list[str] = []

    async def generate():
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            if event["event"] == "on_chat_model_stream" \
                    and event["metadata"].get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield f"data: {json.dumps({'content': chunk, 'conversation_id': str(conv_id)})}\n\n"

        # 流结束 → 只保存 assistant 回复（user 消息已在流开始前保存）
        await conversation_service.add_message(conv_id, "assistant", "".join(full_reply))

        yield f"data: {json.dumps({'conversation_id': str(conv_id)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─────────── 会话管理接口 ───────────

@app.get("/conversations")
async def list_conversations(
    user_id: int,
    last_update_time: datetime | None = None,
    last_id: int | None = None,
    limit: int = 10,
):
    """会话列表（游标分页）"""
    convs = await conversation_service.list_conversations(user_id, last_update_time, last_id, limit)
    return {"data": convs}


@app.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int):
    """获取会话历史消息"""
    messages = await conversation_service.get_history(conversation_id)
    return {"data": messages}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    """删除会话"""
    await conversation_service.delete_conversation(conversation_id)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 十、Human-in-the-loop 节点示例

以 `writing_worker` 为例，在生成草稿后暂停让用户确认：

```python
# app/graph/nodes/writing_worker.py
from langgraph.types import interrupt

async def writing_worker_node(state: AgentState) -> dict:
    """
    写作 Worker：生成草稿 → 暂停 → 等用户确认
    
    【interrupt 执行机制】
    1. 代码执行到 interrupt()，整个图暂停
    2. Checkpointer 保存当前节点的完整状态到 Redis
    3. ainvoke() 返回，/chat 接口检测到 state.next 非空
    4. 前端收到 interrupted=true + payload（草稿内容）
    5. 用户确认后，前端调 /chat/resume，传入 action
    6. Command(resume=action) → Checkpointer 恢复暂停点
    7. interrupt() 返回 action 的值
    8. ⚠️ 注意：恢复时整个节点会重新执行，interrupt() 之前的代码会再跑一遍
    """
    task = state["task_descriptions"].get("writing", "")
    
    # 生成草稿（这段代码在 resume 时会重新执行）
    draft = await generate_draft(task, state["history_messages"])
    
    # 暂停，等用户确认
    user_decision = interrupt({
        "action": "confirm_publish",
        "draft": draft,
        "message": "草稿已生成，是否发布？",
    })
    
    # ← resume 后从这里继续，user_decision = Command(resume=...) 传入的值
    if user_decision == "approve":
        return {"worker_results": [{"worker_name": "writing", "result": draft}]}
    elif user_decision == "reject":
        return {"worker_results": [{"worker_name": "writing", "result": "用户取消了发布"}]}
    else:
        # 用户给了修改意见，重新生成
        revised = await generate_draft(user_decision, state["history_messages"])
        return {"worker_results": [{"worker_name": "writing", "result": revised}]}
```

> **解析**：`interrupt()` 之前的代码在 resume 时会重新执行。如果 `generate_draft` 有副作用（如调外部 API），可以用 state 做幂等判断，避免重复调用。

---

## 十一、完整请求时序图

### 正常对话（无 interrupt）

```
前端 → Java /api/agent/chat → Python /chat
                                 │
                                 ├── 1. ConversationService.create_conversation()  → MySQL INSERT
                                 ├── 2. ConversationService.get_history()          → Redis / MySQL
                                 ├── 3. graph.ainvoke(state, config)               → Checkpointer 自动快照
                                 ├── 4. ConversationService.add_message("user")    → MySQL + Redis
                                 ├── 5. ConversationService.add_message("assistant")→ MySQL + Redis
                                 └── 6. return reply
```

### Human-in-the-loop 对话

```
请求1: 前端 → Java → Python /chat
                       │
                       ├── 1~3 同上
                       ├── 4. writing_worker 里 interrupt()，图暂停
                       ├── 5. Checkpointer 保存暂停点到 Redis
                       ├── 6. ConversationService.add_message("user")
                       └── 7. return {interrupted: true, payload: {draft: "..."}}

前端展示草稿，用户点 "确认发布"

请求2: 前端 → Java → Python /chat/resume  (action="approve")
                       │
                       ├── 1. Command(resume="approve")
                       ├── 2. Checkpointer 从 Redis 恢复暂停点
                       ├── 3. interrupt() 返回 "approve"
                       ├── 4. writing_worker 继续执行 → synthesizer → END
                       ├── 5. ConversationService.add_message("assistant")
                       └── 6. return reply
```

---

## 十二、节点进度推送（前端可视化每一步）

### 目标效果

前端在 AI 回答之前，展示一个实时进度条：

```
✓ 理解问题          ← planner 完成
⟳ 处理中 (信息检索、对话回复)   ← dispatcher 正在执行 search + chat worker
○ 整理回答          ← synthesizer 还没开始
```

### 协议设计

沿用 Java 端已有的 `__PROGRESS__` SSE 协议，前端 `handleProgress()` 不用改：

```
__PROGRESS__:planner                     → Planner 开始（"理解问题中"）
__PROGRESS__:dispatcher:search,chat      → Dispatcher 开始（"处理中: 信息检索、对话回复"）
__PROGRESS__:synthesizer                 → Synthesizer 开始（"整理回答中"）
__PROGRESS__:done                        → 全部完成
```

> **解析**：前端 `AiChat.vue` 的 `handleProgress()` 已经能解析这套协议。Python 端只需在 SSE 流里按同样格式 `yield` 即可，前端零改动。

### 实现方式：`astream_events` 捕获节点进出

LangGraph 的 `astream_events(version="v2")` 会为每个节点的开始和结束触发事件，我们过滤 `on_chain_start` 和 `on_chain_end` 事件即可。

```python
# app/main.py 中的 /chat/stream

# Worker 节点名 → 进度协议名的映射
NODE_TO_PROGRESS = {
    "planner":          "planner",
    "search_worker":    "search",
    "chat_worker":      "chat",
    "analysis_worker":  "analysis",
    "writing_worker":   "writing",
    "synthesizer":      "synthesizer",
}

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = await get_graph()

    conv_id = request.conversation_id
    if conv_id is None:
        conv_id = await conversation_service.create_conversation(request.user_id)

    context = await conversation_service.get_context_for_llm(conv_id)

    initial_state: AgentState = {
        "user_message": request.message,
        "history_messages": context,
        "active_workers": [],
        "task_descriptions": {},
        "worker_results": [],
        "final_reply": "",
    }

    config = {"configurable": {"thread_id": f"conv_{conv_id}"}}
    full_reply: list[str] = []

    async def generate():
        # 先推会话 ID，让前端尽早拿到
        yield f"data: __CONV_ID__:{conv_id}\n\n"

        # 追踪已经发过进度事件的节点，避免重复
        started_nodes: set[str] = set()
        finished_nodes: set[str] = set()
        active_workers: list[str] = []  # planner 输出的 worker 列表

        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")

            # ────── 节点开始 → 推进度 ──────
            if kind == "on_chain_start" and node in NODE_TO_PROGRESS and node not in started_nodes:
                started_nodes.add(node)

                if node == "planner":
                    yield f"data: __PROGRESS__:planner\n\n"

                elif node == "synthesizer":
                    yield f"data: __PROGRESS__:synthesizer\n\n"

                elif node in ("search_worker", "chat_worker", "analysis_worker", "writing_worker"):
                    # 第一个 worker 开始时，一次性发 dispatcher 进度
                    if "dispatcher" not in started_nodes:
                        started_nodes.add("dispatcher")
                        # 从 state 读 planner 输出的 active_workers
                        state_snapshot = await graph.aget_state(config)
                        if state_snapshot and state_snapshot.values:
                            active_workers = state_snapshot.values.get("active_workers", [])
                        workers_str = ",".join(active_workers) if active_workers else node.replace("_worker", "")
                        yield f"data: __PROGRESS__:dispatcher:{workers_str}\n\n"

            # ────── 节点结束 ──────
            if kind == "on_chain_end" and node in NODE_TO_PROGRESS and node not in finished_nodes:
                finished_nodes.add(node)

            # ────── synthesizer 的 LLM 流式输出 → 推内容 ──────
            if kind == "on_chat_model_stream" \
                    and event.get("metadata", {}).get("langgraph_node") == "synthesizer":
                chunk = event["data"]["chunk"].content
                if chunk:
                    full_reply.append(chunk)
                    yield f"data: {chunk}\n\n"

        # 全部完成
        yield f"data: __PROGRESS__:done\n\n"

        # 保存消息
        await conversation_service.add_message(conv_id, "user", request.message)
        await conversation_service.add_message(conv_id, "assistant", "".join(full_reply))

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 事件流时序

一次请求的 SSE 输出序列：

```
data: __CONV_ID__:1234567890              ← 前端拿到会话ID

data: __PROGRESS__:planner               ← 前端显示 "⟳ 理解问题中"
                                           （planner 节点在执行...）

data: __PROGRESS__:dispatcher:search,chat ← 前端显示 "✓ 理解问题" + "⟳ 处理中: 信息检索、对话回复"
                                           （search_worker 和 chat_worker 并行执行...）

data: __PROGRESS__:synthesizer            ← 前端显示 "✓ 处理完成" + "⟳ 整理回答中"
                                           （synthesizer 开始流式输出...）

data: 根据搜索结果，                        ← 逐 token 推送内容
data: Spring Boot 是一个...
data: ...

data: __PROGRESS__:done                   ← 前端所有步骤变 ✓
data: [DONE]                              ← 结束
```

### 关键解析

**Q: 为什么不在每个节点函数里手动 yield 进度？**

因为 `astream_events` 已经帮你做了——LangGraph 在每个节点进出时自动触发 `on_chain_start` / `on_chain_end` 事件，附带 `langgraph_node` 元数据。我们只需要过滤这些事件、映射成协议格式就行，不需要侵入节点代码。

**Q: dispatcher 进度怎么拿到 worker 列表？**

planner 节点完成后会把 `active_workers` 写入 state。当第一个 worker 开始执行时，我们通过 `graph.aget_state(config)` 读 Checkpointer 里的最新快照，就能拿到 planner 输出的 worker 列表。

**Q: Human-in-the-loop 中断时进度怎么处理？**

如果 `writing_worker` 里调了 `interrupt()`，图会暂停。`astream_events` 会结束迭代（因为没有下一个事件了）。此时 `synthesizer` 的进度不会被推出来，前端看到的是：

```
✓ 理解问题
⟳ 处理中 (写作辅助)    ← 停在这里
```

同时返回 interrupt payload，前端切换到"等待用户确认"的 UI。

### 前端已有的处理逻辑（无需修改）

前端 `AiChat.vue` 中 `handleProgress()` 函数已经完整实现了进度条渲染逻辑：

```typescript
// 前端已有代码，无需修改
function handleProgress(aiMsgIndex: number, progressData: string) {
  const msg = messages.value[aiMsgIndex]
  if (!msg.progressSteps) msg.progressSteps = []

  if (progressData === 'planner') {
    msg.progressSteps = [{ key: 'planner', label: '理解问题中', status: 'active' }]
  } else if (progressData.startsWith('dispatcher:')) {
    // Planner ✓，Dispatcher 开始
    plannerStep.status = 'done'
    msg.progressSteps.push({ key: 'dispatcher', label: '处理中', status: 'active', detail: workerLabels })
  } else if (progressData === 'synthesizer') {
    // Dispatcher ✓，Synthesizer 开始
    dispatcherStep.status = 'done'
    msg.progressSteps.push({ key: 'synthesizer', label: '整理回答中', status: 'active' })
  } else if (progressData === 'done') {
    // 全部 ✓
    for (const step of msg.progressSteps) step.status = 'done'
  }
}
```

> Worker 中文名映射也已有：`search → 信息检索`、`analysis → 内容分析`、`writing → 写作辅助`、`chat → 对话回复`

---

## 十二（续）、用户暂停/取消功能

> **暂停 vs 审批**是两回事：审批（interrupt）是有副作用的操作执行前必须确认（如发文章），暂停是用户随时喊停、后续节点不再执行。两者互不干扰，可以同时存在。

### 核心思路

在 State 里加一个 `cancelled` 标志位。用户点暂停 → 调接口写 flag → 后续节点开头检查 flag，为 True 就跳过。

| 需求 | 机制 | 用在哪 |
|------|------|--------|
| 暂停（随时可停） | `cancelled` flag + `aupdate_state` | 所有节点 |
| 审批（执行前确认） | `interrupt()` | 只在有副作用的节点（如 writing） |

### State 新增字段

```python
# app/graph/state.py
class AgentState(TypedDict):
    # ... 已有字段 ...
    
    cancelled: bool  # 用户是否已取消，默认 False
```

### 每个节点开头加检查

```python
# app/graph/nodes/search_worker.py
async def search_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}  # 跳过，空返回
    
    # ... 正常执行逻辑 ...


# app/graph/nodes/chat_worker.py
async def chat_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}
    
    # ... 正常执行逻辑 ...


# app/graph/nodes/analysis_worker.py — 同理
# app/graph/nodes/writing_worker.py — 同理


# app/graph/nodes/synthesizer.py — 特殊处理
async def synthesizer_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        # 用已有的 worker_results 拼一个简短结果，不再调 LLM
        existing = state.get("worker_results", [])
        if existing:
            parts = [r["result"] for r in existing if r.get("result")]
            return {"final_reply": "（已暂停）\n\n" + "\n\n".join(parts)}
        return {"final_reply": "已暂停，未产生结果。"}
    
    # ... 正常执行逻辑 ...
```

> **解析**：
> - worker 节点检查到 cancelled 直接空返回，不浪费 LLM 调用。
> - synthesizer 会把**暂停前已经跑完的 worker 结果**拼起来返回，不至于啥都没有。
> - 正在执行中的节点无法被中途打断（LLM 调用是原子的），但**下一个**要执行的节点会被跳过。

### 暂停接口

```python
# app/main.py

@app.post("/chat/{conversation_id}/cancel")
async def cancel_chat(conversation_id: int):
    """
    用户点了暂停按钮
    
    【原理】
    aupdate_state 会把 cancelled=True 合并进当前图的 state，
    下一个要执行的节点读到这个 flag 就会跳过。
    已经在执行中的节点无法中断，但不会再往后传了。
    """
    graph = await get_graph()
    config = {"configurable": {"thread_id": f"conv_{conversation_id}"}}
    
    await graph.aupdate_state(config, {"cancelled": True})
    return {"status": "ok"}
```

### 前端接入

```typescript
// AiChat.vue — 暂停按钮
async function handleCancel() {
  if (!currentConversationId.value) return
  await request.post(`/api/agent/chat/${currentConversationId.value}/cancel`)
  // SSE 流会在后续节点跳过后自然结束
}
```

### SSE 流式场景下的时序

```
用户发消息，流式开始：
  data: __CONV_ID__:123456
  data: __PROGRESS__:planner
  （planner 执行中...）

planner 完成，dispatcher 分发 search + chat 并行：
  data: __PROGRESS__:dispatcher:search,chat
  （search_worker 和 chat_worker 执行中...）

───── 用户此时点了暂停 → POST /cancel → state.cancelled = True ─────

  search_worker 已经在跑了，会跑完（LLM 调用无法中断）
  chat_worker 如果还没开始 → 检查 cancelled → 空返回

  → synthesizer 检查 cancelled = True
  → 拼接已有结果（只有 search 的）+ "（已暂停）"前缀

  data: __PROGRESS__:synthesizer
  data: （已暂停）\n\n搜索结果...
  data: __PROGRESS__:done
  data: [DONE]
```

> **解析**：暂停不是瞬时的，当前正在执行的 LLM 调用会跑完。但下一个节点会被跳过，synthesizer 会用已有结果快速收尾。对用户来说，点暂停后几秒内流就结束了。

---

## 十三、Redis Key 全景

| Key 模式 | 来源 | 含义 | TTL |
|----------|------|------|-----|
| `py_conv:{conversation_id}` | ConversationService | 会话历史消息缓存 | 2 小时 |
| `checkpointer:*` | LangGraph AsyncRedisSaver | 图节点快照 + interrupt 暂停点 | 由 LangGraph 管理 |
| `article_cards:{conversation_id}` | 业务逻辑 | 文章卡片临时存储 | 按需设置 |

三者 key 前缀不同，互不干扰。

> **注意**：Java 旧方案中 `article_cards:{conversation_id}` 用 Redis 做 Tool → 接口层的卡片中转。Python Agent 接管后改用 State 传递，不再需要这个 key，见下一节。

---

## 十三（续）、文章卡片传递：旁路传递（Side-channel）

### 设计原则：给 LLM 的 ≠ 给前端的

主流产品（ChatGPT、Perplexity、Kimi）搜索后展示的引用卡片，**从不经过 LLM**。原因：

1. 卡片的 JSON 结构（articleId、cover URL、viewCount）对 LLM 生成回复毫无帮助
2. 拼进 ToolMessage 纯属浪费 token，5 张卡片约 800~1200 token
3. LLM 可能被 JSON 干扰，把 URL 或数字"编"进回复里

正确做法是 **Side-channel（旁路）**：

```
                   ┌─── 文本摘要（标题+简介） ───→ LLM → 生成回复
ES 搜索结果 ──→   │
                   └─── 结构化卡片数据 ──────────→ State → SSE → 前端渲染
```

LLM 只看精简文本，卡片走独立的数据通道，**互不干扰**。

### 旧方案回顾

| 方案 | 路径 | 问题 |
|------|------|------|
| Java 旧方案 | Tool → Redis → 接口层取 | Python 接管后 Redis 通道不通，5 分钟过期 |
| ~~文档旧草案~~ | ~~Tool 返回文本尾部拼 `__CARDS__:JSON`~~ | ~~JSON 进 ToolMessage 浪费 token，LLM 白看~~ |

### 新方案：Worker 节点旁路构建卡片

**核心思路**：search_worker 本身就调了 ES 搜索拿到原始结果，直接在 worker 层构建卡片写入 State，**Tool 完全不碰卡片**。

```
search_worker:
  ├── ES 粗检索 + Reranker 精排 → ranked_results（原始搜索结果）
  ├── Tool 调用（如有）→ 返回纯文本，不含卡片
  ├── 从 ranked_results 构建 article_cards → 写入 State（旁路）
  └── LLM 只看文本摘要 → worker_results
         ↓
接口层从 State 取卡片 → SSE 推给前端 + 存 MySQL
```

对比三种方案：

| | Java 旧方案 | ~~旧草案~~ | **新方案（旁路）** |
|--|--|--|--|
| 卡片构建位置 | Tool | Tool | **Worker 节点** |
| 卡片经过 LLM？ | 否（Redis 绕过） | **是（浪费 token）** | **否** |
| 中转方式 | Redis | ToolMessage 文本拼接 | **State 直传** |
| 需要解析标记？ | 否 | 是（`__CARDS__:`） | **否** |
| 历史持久化 | ❌ Redis 过期 | ✅ MySQL | ✅ **MySQL** |

### 1. State 加字段

```python
# app/graph/state.py
from operator import add

class AgentState(TypedDict):
    # ... 已有字段 ...
    
    # 文章卡片（搜索到的文章，给前端展示卡片用，不经过 LLM）
    # Annotated[list, add]：多个 worker 返回的卡片自动合并
    article_cards: Annotated[list[dict], add]
```

### 2. Tool 保持纯文本，不动

```python
# app/tools/article_tool.py — 不需要改动
# Tool 只返回给 LLM 看的文本摘要，不包含任何卡片 JSON

@tool
async def search_articles(query: str) -> str:
    """搜索平台内的技术文章。"""
    results = await _es.search(query, page_size=5)
    if not results:
        return "平台内未找到相关文章"
    # 只返回标题+摘要，LLM 用得到的信息
    return "\n".join([f"- [{r['title']}] {r.get('summary', '')[:200]}" for r in results])
```

### 3. Worker 节点旁路构建卡片

卡片在 search_worker 中**直接从 ES 搜索结果构建**，不从 Tool 返回值里解析。

```python
# app/graph/nodes/search_worker.py

def _build_cards_from_results(results: list[dict]) -> list[dict]:
    """从 ES 原始搜索结果构建前端卡片数据（旁路，不经过 LLM）"""
    cards = []
    for r in results:
        card = {
            "articleId": str(r.get("article_id", "")),
            "title": r.get("title", ""),
            "coverImage": r.get("cover", ""),
            "authorName": r.get("author_name", ""),
            "viewCount": r.get("view_count", 0),
            "likeCount": r.get("like_count", 0),
        }
        if card["articleId"]:
            cards.append(card)
    return cards


async def search_worker_node(state: AgentState) -> dict:
    # ... 现有逻辑：query rewrite → 粗检索 → Reranker 精排 ...
    
    # [旁路] 从精排结果直接构建卡片，不经过 LLM
    article_cards = _build_cards_from_results(ranked)
    
    # ... 现有逻辑：LLM + tool 调用 → response ...
    
    return {
        "worker_results": [{
            "worker_name": "search",
            "result": response.content  # LLM 从不看卡片 JSON
        }],
        "article_cards": article_cards,  # 旁路写入 State
    }
```

> **关键**：`ranked` 是 `execute_coarse_retrieval()` + `reranker_service.rerank()` 之后的结果，search_worker 已经持有它了。直接用它构建卡片，不需要再从 Tool 返回文本里解析。

### 4. 接口层从 State 取卡片

**非流式接口**：

```python
# app/main.py — /chat 接口末尾
    reply = result.get("final_reply", "抱歉，处理出错了")
    article_cards = result.get("article_cards", [])
    
    # 去重（多路检索可能命中同一篇文章）
    seen_ids = set()
    unique_cards = []
    for card in article_cards:
        aid = card.get("articleId")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            unique_cards.append(card)
    
    await conversation_service.add_message(
        conv_id, "assistant", reply,
        article_cards=unique_cards or None,
    )
    
    return ChatResponse(
        reply=reply,
        conversation_id=str(conv_id),
        articles=unique_cards,
    )
```

**流式接口**：

```python
# app/main.py — /chat/stream 的 generate() 末尾

        # 从 checkpointer 读最终 state，取卡片（旁路数据）
        final_state = await graph.aget_state(config)
        article_cards = final_state.values.get("article_cards", []) if final_state else []
        
        # 去重
        seen_ids = set()
        unique_cards = []
        for card in article_cards:
            aid = card.get("articleId")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                unique_cards.append(card)
        
        if unique_cards:
            yield _sse(f"__ARTICLES__:{json.dumps(unique_cards, ensure_ascii=False)}")
        
        await conversation_service.add_message(
            conv_id, "assistant", "".join(full_reply),
            article_cards=unique_cards or None,
        )
```

### 数据流全景

```
用户发消息 "搜一下 Spring Boot"
         ↓
planner → active_workers: ["search"]
         ↓
search_worker:
  ├── query_rewrite → 粗检索 → Reranker → ranked = [5篇文章]
  │
  ├── [旁路] _build_cards_from_results(ranked)
  │     → article_cards = [{articleId, title, cover, ...}, ...]
  │     → 写入 State（不经过 LLM，零 token 消耗）
  │
  ├── [主路] LLM 看到的只有：
  │     SystemMessage: "你是信息检索助手..."
  │     HumanMessage: "任务：... RAG参考资料：- [标题] 摘要..."
  │     → response.content = "找到以下相关文章..."
  │     → worker_results（synthesizer 用这个生成最终回复）
  │
  └── return {"worker_results": [...], "article_cards": [...]}
         ↓
State: article_cards = [5张卡片]（reducer 自动合并）
         ↓
synthesizer → final_reply = "根据搜索结果，Spring Boot 是..."
  （synthesizer 从不碰 article_cards，它只看 worker_results）
         ↓
接口层:
  ├── aget_state() → article_cards → 去重
  ├── SSE: __ARTICLES__:[{...}]     ← 前端渲染卡片
  ├── SSE: 文本内容流                ← 前端渲染 Markdown
  ├── add_message(article_cards=...)  ← MySQL 持久化（历史可查）
  └── SSE: [DONE]

查看历史 → SELECT article_cards FROM ai_message → 卡片永久可用
```

---

## 十四、Java 端简化

Python Agent 接管会话管理后，Java 端的 `AgentService` + `AiConversationService` 简化为纯转发层。每个 Controller 接口对应转发到 Python 的不同端点。

### 接口映射表

| Java 端接口 | 方法 | 转发到 Python 端 | 说明 |
|------------|------|-----------------|------|
| `/api/agent/chat` | POST | `POST /chat` | 非流式聊天 |
| `/api/agent/chat/stream` | POST | `POST /chat/stream` | 流式聊天（SSE） |
| `/api/agent/chat/resume` | POST | `POST /chat/resume` | Human-in-the-loop 恢复 |
| `/api/agent/chat/{id}/cancel` | POST | `POST /chat/{id}/cancel` | 暂停执行 |
| `/api/agent/conversations` | GET | `GET /conversations?user_id=` | 会话列表 |
| `/api/agent/conversations/{id}/messages` | GET | `GET /conversations/{id}/messages` | 历史消息 |
| `/api/agent/conversations/{id}` | DELETE | `DELETE /conversations/{id}` | 删除会话 |

### AgentService 简化版

```java
// AgentService.java — 纯转发，不再持有任何 AI 逻辑
// 非流式用 RestTemplate（简洁），流式用 WebClient（原生支持 SSE）
@Service
@Slf4j
public class AgentService {

    private static final String PYTHON_AGENT_URL = "http://python-agent:8000";

    private final RestTemplate restTemplate = new RestTemplate();
    private final WebClient webClient = WebClient.create(PYTHON_AGENT_URL);

    /**
     * 非流式聊天 → 转发到 Python /chat
     */
    public AiChatVO chat(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
        Map<String, Object> body = Map.of(
                "user_id", userId,
                "conversation_id", conversationId,  // 可为 null，Python 端自动创建
                "message", userMessage,
                "image_paths", imagePaths != null ? imagePaths : List.of()
        );
        String response = restTemplate.postForObject(PYTHON_AGENT_URL + "/chat", body, String.class);
        return JSON.parseObject(response, AiChatVO.class);
    }

    /**
     * 流式聊天 → 转发 Python /chat/stream 的 SSE 流
     */
    public Flux<String> chatStream(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("conversation_id", conversationId);
        body.put("message", userMessage);
        body.put("image_paths", imagePaths);

        return webClient.post().uri("/chat/stream")
                .bodyValue(body)
                .retrieve()
                .bodyToFlux(String.class);
    }

    /**
     * Human-in-the-loop 恢复 → 转发到 Python /chat/resume
     */
    public AiChatVO chatResume(Long conversationId, Long userId, String action) {
        Map<String, Object> body = Map.of(
                "user_id", userId,
                "conversation_id", conversationId,
                "action", action
        );
        String response = restTemplate.postForObject(PYTHON_AGENT_URL + "/chat/resume", body, String.class);
        return JSON.parseObject(response, AiChatVO.class);
    }

    /**
     * 暂停执行 → 转发到 Python /chat/{id}/cancel
     */
    public void cancelChat(Long conversationId) {
        restTemplate.postForObject(
                PYTHON_AGENT_URL + "/chat/" + conversationId + "/cancel", null, String.class);
    }
}
```

> **解析**：
> - **非流式**用 `RestTemplate`：一行搞定，Spring Boot 自带，无额外依赖。
> - **流式**用 `WebClient`：原生支持 SSE 流，返回 `Flux<String>` 直接给 Controller。项目已有 `spring-boot-starter-webflux`（因为用了 `Flux` + `Schedulers`），不需要加依赖。
> - 两者混用是 Spring 项目的常见做法：`RestTemplate` 负责简单同步请求，`WebClient` 负责流式/异步场景。

### AiConversationService 简化版

```java
// AiConversationService.java — 会话管理也转发给 Python
@Service
public class AiConversationService {

    private static final String PYTHON_AGENT_URL = "http://python-agent:8000";
    private final RestTemplate restTemplate = new RestTemplate();

    /**
     * 会话列表 → 转发 Python GET /conversations
     */
    public List<AiConversation> getUserConversationsWithCursor(Long userId, LocalDateTime lastUpdateTime,
                                                               Long lastId, int limit) {
        String url = PYTHON_AGENT_URL + "/conversations?user_id=" + userId + "&limit=" + limit;
        if (lastUpdateTime != null) url += "&last_update_time=" + lastUpdateTime;
        if (lastId != null) url += "&last_id=" + lastId;

        String response = restTemplate.getForObject(url, String.class);
        return JSON.parseObject(response).getList("data", AiConversation.class);
    }

    /**
     * 历史消息 → 转发 Python GET /conversations/{id}/messages
     */
    public List<AiMessage> getContext(Long conversationId) {
        String response = restTemplate.getForObject(
                PYTHON_AGENT_URL + "/conversations/" + conversationId + "/messages", String.class);
        return JSON.parseObject(response).getList("data", AiMessage.class);
    }

    /**
     * 删除会话 → 转发 Python DELETE /conversations/{id}
     */
    public void clearContext(Long conversationId) {
        restTemplate.delete(PYTHON_AGENT_URL + "/conversations/" + conversationId);
    }
}
```

### ResumeParam 新增

```java
// ResumeParam.java — Human-in-the-loop 恢复请求参数
@Data
public class ResumeParam {
    
    /**
     * 会话ID
     */
    private Long conversationId;
    
    /**
     * 用户操作：approve / reject / 用户输入的修改意见
     */
    private String action;
}
```

### Controller 基本不变

```java
// AgentController.java — 接口签名不变，只是 service 层变成了转发
@PostMapping("/chat")
public ResponseVO chat(@RequestBody AiChatParam param) {
    Long userId = UserContext.getUserId();
    return ResponseVO.success(agentService.chat(
            param.getConversationId(), userId, param.getMessage(), param.getImagePaths()));
}

@PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<String> chatStream(@RequestBody AiChatParam param) {
    Long userId = UserContext.getUserId();
    return agentService.chatStream(
            param.getConversationId(), userId, param.getMessage(), param.getImagePaths());
}

// 新增：Human-in-the-loop 恢复
@PostMapping("/chat/resume")
public ResponseVO chatResume(@RequestBody ResumeParam param) {
    Long userId = UserContext.getUserId();
    return ResponseVO.success(agentService.chatResume(
            param.getConversationId(), userId, param.getAction()));
}

// 新增：暂停
@PostMapping("/chat/{conversationId}/cancel")
public ResponseVO cancelChat(@PathVariable Long conversationId) {
    agentService.cancelChat(conversationId);
    return ResponseVO.success(null);
}

// ===== 以下是 AiConversationService 相关接口（原有，转发到 Python） =====

@GetMapping("/conversations")
public ResponseVO getConversations(
        @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime lastUpdateTime,
        @RequestParam(required = false) Long lastId,
        @RequestParam(defaultValue = "10") int limit) {
    Long userId = UserContext.getUserId();
    List<AiConversation> list = aiConversationService.getUserConversationsWithCursor(
            userId, lastUpdateTime, lastId, limit);
    return ResponseVO.success(list);
}

@GetMapping("/conversations/{conversationId}/messages")
public ResponseVO getMessages(@PathVariable Long conversationId) {
    return ResponseVO.success(aiConversationService.getContext(conversationId));
}

@DeleteMapping("/conversations/{conversationId}")
public ResponseVO<Void> deleteConversation(@PathVariable Long conversationId) {
    aiConversationService.clearContext(conversationId);
    return ResponseVO.success(null);
}
```

> **解析**：
> - **前端的请求路径不变**，还是打 Java 的 `/api/agent/*`，Java 做鉴权（`UserContext.getUserId()`）后转发给 Python。
> - **Python 端不做鉴权**，user_id 由 Java 端注入，Python 信任 Java 传过来的值。
> - **非流式**用 `RestTemplate`（一行搞定），**流式**用 `WebClient`（原生支持 SSE），两者混用是 Spring 常见做法。
> - 原来 Java 端的 `AgentService` 里的 Planner、Dispatcher、Worker、Synthesizer 全部删掉，Graph 逻辑全在 Python 端。

---

## 十五、总结

| 组件 | 职责 | 存储介质 |
|------|------|----------|
| **ConversationService** | 聊天记录 CRUD、摘要压缩、Token 计数、会话列表 | MySQL（持久）+ Redis（缓存） |
| **token_utils** | Token 计数、预算截断 | 纯计算，无存储 |
| **Checkpointer** | interrupt/resume 的图执行断点 | Redis（LangGraph 自动管理） |
| **AgentState.history_messages** | 由 `get_context_for_llm()` 构建注入 | 内存（每次请求组装） |

### 上下文管理策略一句话总结

游标后未总结消息数达到 30 时，保留最近 10 条原文，只总结前面的 20 条，游标前移。下次读上下文只需 summary + `WHERE message_id > 游标` 即可，压缩后仍有 10 条近期原文保底。MySQL 里完整保留所有原始消息不删除，每条消息带 `token_count`，会话级别有 `total_tokens` 累计统计。

### 数据流全景

```
add_message()
  ├── tiktoken 计算 token_count
  ├── INSERT ai_message (带 token_count)
  ├── UPDATE ai_conversation (message_count + total_tokens)
  ├── COUNT(message_id > summary_upto_msg_id) >= SUMMARY_TRIGGER?
  │    └── 是 → _maybe_compress():
  │         读游标后全部消息（30条）
  │         保留最近 KEEP_RECENT=10 条，总结前 20 条 → LLM 生成摘要
  │         → UPDATE summary + summary_upto_msg_id = 第20条的ID
  └── 清 Redis 缓存

get_context_for_llm()
  ├── 读 summary + summary_upto_msg_id
  ├── summary → 注入为 system 消息（如果有）
  ├── SELECT ... WHERE message_id > summary_upto_msg_id（读未总结的消息）
  └── 返回 [摘要] + [游标后的全部消息]（压缩后仍有10条原文）
```
