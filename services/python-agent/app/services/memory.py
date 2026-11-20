import json
import logging
from datetime import datetime

from elasticsearch.helpers import async_bulk

from app.clients.es_client import BaseEsClient
from app.clients.mysql_client import db
from app.clients.redis_client import RedisClient
from app.services.embedding import EmbeddingService

log = logging.getLogger(__name__)

PROFILE_SIGNAL_PATTERNS = [
    "记住", "以后默认", "以后都", "我一般", "我平时", "我喜欢",
    "我是", "我做", "我用", "别再", "请默认",
]

HISTORY_SIGNAL_PATTERNS = [
    "你还记得", "按我之前", "继续上次", "根据我的背景", "根据我的偏好",
]

LOW_VALUE_PATTERNS = [
    "好的", "收到", "谢谢", "嗯嗯", "ok", "OK",
]
# ─── 记忆个性化 Prompt（注入给 Worker） ───
MEMORY_CONTEXT_TEMPLATE = """[用户画像]
{profile_summary}

[相关历史记忆]
{relevant_memories}"""

class MemoryService:
    def __init__(self):
        self._embedding = EmbeddingService()
        self._es = BaseEsClient()
        self._redis = RedisClient()
    async def extract_and_store(self, user_id, conversation_id, messages, *, job=None, jobs=None):
        """Compatibility guard: historical-event extraction is retired."""
        return

    async def sync_changes(self, values, removed):
        """Best-effort candidate-index maintenance after authoritative DB commit."""
        try:
            if removed:
                _, errors = await async_bulk(self._es.client, [{"_op_type": "delete", "_index": "user_memories", "_id": str(mid)}
                                                              for mid in removed], raise_on_error=False)
                if any(next(iter(error.values())).get("status") != 404 for error in errors):
                    return False
            if not values:
                return True
            vectors = await self._embedding.aembed_batch([r["content"] for r in values])
            now = datetime.now()
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
                        "memory_type": r.get("type", "decision"),
                        "scope": r.get("scope", "user"),
                        "scope_conversation_id": r.get("scope_cid"),
                    },
                }
                for r, vec in zip(values, vectors)
            ]
            ok,errors = await async_bulk(self._es.client,actions,raise_on_error=False)
            user_id = values[0]["uid"]
            if errors:
                log.warning("记忆写入 ES 部分失败: %s", errors)
                return False
            else:
                log.info("批量写入 ES: user=%s, count=%d", user_id, ok)

        except Exception as e:
            log.warning("记忆批量写入 ES 失败: %s", e)
            return False

        log.info("同步记忆候选: count=%d", len(values))
        return True

    async def load_context(self, user_id, conversation_id):
        from app.services.memory_policy import memory_policy_service
        return await memory_policy_service.load_context(user_id, conversation_id)
    async def _get_profile(self, user_id: int) -> dict | None:
        """获取用户画像"""
        row = await db.fetch_one(
            "SELECT * FROM user_profile WHERE user_id = :uid",
            {"uid": user_id},
        )
        if not row:
            return None
        return dict(row._mapping)
    async def recall_details(self, user_id: int, query: str, top_k: int = 5, *, strict: bool = False,
                             conversation_id: int | None = None, include_profile: bool = True) -> dict:
        """ES selects candidates; MySQL owns identity and current content.

        Explicit actions use strict=True so an unavailable index is not
        reported as a successful lookup with no matches.
        """
        if not user_id:
            return {"profile_summary": "", "memories": []}
        if strict:
            from app.services.memory_policy import memory_policy_service
            await memory_policy_service.flush_pending_index(user_id)
        top_k = max(1, min(5, top_k))
        log.info("用户画像查询%d", user_id)
        # 1. ES 向量检索，只拿候选 memory_id
        candidates = await self._search_memories(user_id, query, top_k, strict=strict, conversation_id=conversation_id)

        # 2. 获取用户画像
        profile = await self._get_profile(user_id) if include_profile else None
        profile_summary = (profile.get("summary") or "").strip() if profile else ""
        if profile_summary in ("暂无用户画像", "新用户，暂无画像"):
            profile_summary = ""

        # 3. 拿候选 ID 去 MySQL 查最新数据
        relevant_memories = []
        if candidates:
            memory_ids = [c["memory_id"] for c in candidates]
            placeholders = ", ".join(f":id{i}" for i in range(len(memory_ids)))
            params = {f"id{i}": mid for i, mid in enumerate(memory_ids)}
            params["uid"] = user_id
            params["cid"] = conversation_id

            rows = await db.fetch_all(
                f"SELECT memory_id, content, importance, access_count, source_conversation_id,memory_type,scope,memory_key "
                f"FROM user_memory WHERE user_id = :uid AND status='active' AND memory_type='decision' "
                f"AND (scope='user' OR (scope='conversation' AND scope_conversation_id=:cid)) AND memory_id IN ({placeholders})",
                params,
            )
            # 如果 MySQL 里已经不存在（被 decay 删了），就自然过滤掉了
            memory_by_id = {str(r._mapping["memory_id"]): dict(r._mapping) for r in rows}
            relevant_memories = [memory_by_id[str(mid)] for mid in dict.fromkeys(memory_ids)
                                 if str(mid) in memory_by_id]

            # 4. 更新访问计数（只对 MySQL 里还存在的）
            if relevant_memories:
                alive_ids = [m["memory_id"] for m in relevant_memories]
                alive_ph = ", ".join(f":aid{i}" for i in range(len(alive_ids)))
                alive_params = {f"aid{i}": mid for i, mid in enumerate(alive_ids)}
                alive_params["uid"] = user_id
                await db.execute(
                    f"UPDATE user_memory SET access_count = access_count + 1 "
                    f"WHERE user_id = :uid AND status='active' AND memory_id IN ({alive_ph})",
                    alive_params,
                )

        return {"profile_summary": profile_summary, "memories": relevant_memories}

    async def recall(self, user_id: int, query: str, top_k: int = 5) -> str:
        """Keep automatic request-time recall compatible with its text context."""
        recalled = await self.recall_details(user_id, query, top_k)
        relevant_memories = recalled["memories"]
        profile_summary = recalled["profile_summary"]
        if not relevant_memories and not profile_summary:
            return ""
        if not relevant_memories:
            mem_text = "无相关历史记忆"
        else:
            mem_text = "\n".join(
                f"- {m['content']} (重要性: {m['importance']:.1f})"
                for m in relevant_memories
            )

        return MEMORY_CONTEXT_TEMPLATE.format(
            profile_summary=profile_summary or "暂无用户画像",
            relevant_memories=mem_text,
        )
    async def _search_memories(
        self, user_id: int, query: str, top_k: int = 5, *, strict: bool = False, conversation_id: int | None = None
    ) -> list[dict]:
        """向量搜索用户记忆"""
        try:
            query_vector = await self._embedding.aembed(query)
            clauses = [{"term": {"user_id": user_id}}, {"term": {"memory_type": "decision"}}]
            if conversation_id is not None:
                clauses.append({"bool": {"should": [{"term": {"scope": "user"}},
                    {"term": {"scope_conversation_id": conversation_id}}], "minimum_should_match": 1}})
            else:
                clauses.append({"term": {"scope": "user"}})
            filters = {"bool": {"filter": clauses}}
            resp = await self._es.client.search(
                index="user_memories",
                knn={
                    "field": "content_vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": top_k * 3,
                    "filter": filters,
                },
                size=top_k,
            )
            results = []
            for hit in resp.get("hits", {}).get("hits", []):
                results.append({
                    "memory_id": hit["_source"]["memory_id"],
                    "score": hit["_score"],
                })
            return results
        except Exception as e:
            log.warning("记忆检索失败: %s", e)
            if strict:
                raise
            return []
    #判断条件
    # 判断用户画像信号
    def has_profile_signal(self,text:str)->bool:
        if not text:
            return False
        return  any(k in text for k in PROFILE_SIGNAL_PATTERNS)
    #判断历史信号
    def has_history_signal(self,text:str)->bool:
        if not text:
            return False
        return  any(k in text for k in HISTORY_SIGNAL_PATTERNS)
    #判断是否需要调用记忆
    def should_recall(self,is_new_conversation:bool,user_text:str)->bool:
        if is_new_conversation:
            return True
        if self.has_profile_signal(user_text):
            return True
        if self.has_history_signal(user_text):
            return True
        return False
    def is_low_value_round(self,user_text:str,assistant_text:str)->bool:
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if(user_text in LOW_VALUE_PATTERNS):
            return True
        if(len(user_text)<=6 and len(assistant_text)<=20):
            return True
        return False
    def _find_last_user_text(self,messages:list[dict])->str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return  ""

    def _count_user_turns(self, messages: list[dict]) -> int:
        return sum(1 for msg in messages if msg.get("role") == "user")
    #提取条件
    async def should_extract(
            self,
            conversation_id: int,
            messages: list[dict],
            assistant_text: str,
            interrupted: bool,
            total_user_turns: int | None = None,
    ) -> bool:
        # Explicit profile/constraint/decision changes belong to Main. Ordinary
        # chats remain in conversation history/summary, never extracted memories.
        return False
# ─── 全局单例 ───
memory_service = MemoryService()
