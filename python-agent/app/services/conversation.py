import json
import logging
import re
from datetime import datetime

from app.clients.mysql_client import db
from app.clients.redis_client import RedisClient
from app.config import get_llm
from app.utils.snowflake import snowflake
from app.utils.token_utils import count_tokens, truncate_to_token_budget

log = logging.getLogger(__name__)

SUMMARY_BUDGET  = 2000   # 摘要最多占用的 token
SUMMARY_TRIGGER = 30     # 游标后未总结消息数达到此值时触发压缩
KEEP_RECENT     = 10     # 压缩时保留最近 10 条不总结
CACHE_TTL       = 7200   # Redis 缓存 2 小时

def _snake_to_camel(s: str) -> str:
    """snake_case → camelCase (e.g. conversation_id → conversationId)"""
    parts = s.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])

def _to_camel_dict(d: dict) -> dict:
    """将 dict 的所有 key 从 snake_case 转为 camelCase"""
    return {_snake_to_camel(k): v for k, v in d.items()}


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
    async def create_conversation(self, user_id:int)->int:
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
        return [_to_camel_dict(dict(r._mapping)) for r in rows]

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
        await self._redis.delete(self._llm_cache_key(conversation_id))

    async def get_context_for_llm(self, conversation_id: int) -> list[dict]:
        """
        构建注入给 LLM 的上下文消息列表

        返回格式：[摘要(system)] + [游标之后的未总结消息]

        【流程】
        1. 读 summary + summary_upto_msg_id
        2. 若有摘要 → 放最前面
        3. 读 message_id > summary_upto_msg_id 的所有消息
           若游标为 NULL → 从未压缩过，读全部消息
        """
        cache = await self._redis.get(self._llm_cache_key(conversation_id))
        if cache:
            return json.loads(cache)
        log.info("从 Redis 获取会话上下文: conv=%s", conversation_id)
        context: list[dict] = []

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
        await self._redis.set(self._llm_cache_key(conversation_id), json.dumps(context,ensure_ascii=False,default=str),ex=CACHE_TTL)
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
                "imagePaths": m.get("image_paths"),
                "articleCards": m.get("article_cards"),
                "draftArticleId": (
                    str(m["draft_article_id"]) if m.get("draft_article_id") else None
                ),  # ← 新增，转 string 避免 JS 精度丢失
                "tokenCount": m.get("token_count", 0),
                "createTime": m.get("create_time"),
            }
            for m in messages
        ]
        await self._save_cache(conversation_id, result)
        return result

    async def add_message(
            self, conversation_id: int, role: str, content: str,
            image_paths: list[str] | None = None,
            article_cards: list[dict] | None = None,
            draft_article_id: int | None = None,
    ):
        """
        添加一条消息：计算token → 写 MySQL → 更新统计 → 检查是否触发摘要 → 刷缓存

        对应 Java: addMessage()
        """
        msg_id = snowflake.next_id()
        now = datetime.now()
        token_count = count_tokens(content)
        ctx_cached = await  self._redis.get(self._llm_cache_key(conversation_id))
        if ctx_cached:
            ctx = json.loads(ctx_cached)
            ctx.append({"role": role, "content": content})
            await self._redis.set(self._llm_cache_key(conversation_id),
                                  json.dumps(ctx,ensure_ascii=False,default=str),ex=CACHE_TTL)
        # 1. 写 MySQL（带 token_count）
        await db.execute(
            """
            INSERT INTO ai_message
                (message_id, conversation_id, role, content, token_count, 
                 image_paths, article_cards,draft_article_id, create_time)
            VALUES
                (:mid, :cid, :role, :content, :tc, :imgs, :cards,:draft_aid, :now)
            """,
            {
                "mid": msg_id,
                "cid": conversation_id,
                "role": role,
                "content": content,
                "tc": token_count,
                "imgs": json.dumps(image_paths, ensure_ascii=False) if image_paths else None,
                "cards": json.dumps(article_cards, ensure_ascii=False) if article_cards else None,
                "draft_aid": draft_article_id,
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
        # 4. 检查是否需要触发摘要压缩（统计游标后未总结消息数）
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
        """游标方案：保留最近 KEEP_RECENT 条不总结，只总结前面的"""
        conv = await db.fetch_one(
            "SELECT summary, summary_upto_msg_id FROM ai_conversation WHERE conversation_id = :cid",
            {"cid": conversation_id},
        )
        if not conv:
            return
        old_summary = conv._mapping["summary"]
        cursor_id = conv._mapping["summary_upto_msg_id"]

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
        new_cursor_id = to_summarize[-1]["message_id"]

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

        llm = get_llm(temperature=0)
        result = await llm.ainvoke(prompt)
        new_summary = result.content

        summary_tokens = count_tokens(new_summary)
        if summary_tokens > SUMMARY_BUDGET:
            new_summary = truncate_to_token_budget(new_summary, SUMMARY_BUDGET)
            summary_tokens = SUMMARY_BUDGET

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
        await self._redis.delete(self._llm_cache_key(conversation_id))

    # ═══════════════════ 私有方法 ═══════════════════

    def _cache_key(self, conversation_id: int) -> str:
        return f"py_conv:{conversation_id}"

    def _llm_cache_key(self, conversation_id: int) -> str:
        return f"py_ctx:{conversation_id}"
    async def _save_cache(self, conversation_id: int, messages: list[dict]):
        await self._redis.set(
            self._cache_key(conversation_id),
            json.dumps(messages, ensure_ascii=False, default=str),
            ex=CACHE_TTL,
        )

    async def _get_all_messages(self, conversation_id: int) -> list[dict]:
        """读全部消息（仅给前端 get_history 用）"""
        rows = await db.fetch_all(
            """
            SELECT role, content, token_count, image_paths, article_cards,draft_article_id, create_time
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
                "draft_article_id": r._mapping["draft_article_id"],
                "create_time": str(r._mapping["create_time"]) if r._mapping["create_time"] else None,
            }
            for r in rows
        ]