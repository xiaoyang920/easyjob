import json
import logging
from datetime import datetime
from typing import Optional

from elasticsearch.helpers import async_bulk
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.clients.es_client import BaseEsClient
from app.clients.mysql_client import db
from app.clients.redis_client import RedisClient
from app.config import get_llm
from app.services.embedding import EmbeddingService
from app.utils.snowflake import snowflake

log = logging.getLogger(__name__)

class MemoryItem(BaseModel):
    content: str = Field(description="记忆内容")
    importance: float = Field(default=0.5,description="记忆重要程度 0-1")


class ProfileUpdates(BaseModel):
    tech_stack: list[str] = Field(default_factory=list, description="识别到的技术栈")
    interests: list[str] = Field(default_factory=list, description="识别到的兴趣爱好")
    experience: Optional[str] = Field(default=None, description="junior|mid|senior，无法判断则不填")
    preferences: dict = Field(default_factory=dict, description="对话偏好，如 {\"style\": \"practical\", \"detail\": \"high\"}")


class MemoryExtractResult(BaseModel):
    # LLM 输出有时是字符串列表 ["xxx", "yyy"]，有时是对象列表 [{"content":"xxx","importance":0.5}]
    # 下面 validator 会把两种都归一成 MemoryItem 列表
    memories: list[MemoryItem] = Field(default_factory=list)
    profile_updates: ProfileUpdates = Field(default_factory=ProfileUpdates)

    @classmethod
    def model_validate(cls, obj, **kwargs):  # pydantic v2 入口
        if isinstance(obj, dict):
            # memories: 字符串列表 → MemoryItem 列表
            mems = obj.get("memories", [])
            if isinstance(mems, list):
                obj["memories"] = [
                    m if isinstance(m, dict) else {"content": str(m), "importance": 0.5}
                    for m in mems
                ]
            # profile_updates: 字符串列表 → 全部塞到 interests 里兜底
            pu = obj.get("profile_updates")
            if isinstance(pu, list):
                obj["profile_updates"] = {"interests": [str(x) for x in pu]}
            elif pu is None:
                obj["profile_updates"] = {}
        return super().model_validate(obj, **kwargs)
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
EXTRACT_INTERVAL_TURNS = 6
EXTRACT_COOLDOWN_SECONDS = 300
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
    def __init__(self):
        self._embedding = EmbeddingService()
        self._es = BaseEsClient()
        self._llm = get_llm(temperature=0.3)
        self._redis = RedisClient()
    async def extract_and_store(
            self,user_id:int,conversation_id:int,messages:list[dict]
    ):
        #如果聊天记录过少，则不进行记忆提取
        if len(messages) < 4:
            return
        #构建对话文本
        conv_text = "\n".join(
            f"{m.get('role','user')}:{m.get('content','')}"
            for m in messages[-20:]
        )

        try:
            structured_llm = self._llm.with_structured_output(MemoryExtractResult, method="function_calling")
            data = await structured_llm.ainvoke(
                [SystemMessage(content=MEMORY_EXTRACT_PROMPT.format(conversation=conv_text))]
            )
        except Exception as e:
            log.warning("记忆提取失败: %s", e)
            return
        if data.memories:
            now = datetime.now()
            values = [
                {
                    "mid": snowflake.next_id(),
                    "uid": user_id,
                    "content": mem.content,
                    "imp": mem.importance,
                    "src_conv": conversation_id,
                    "now": now,
                }
                for mem in data.memories
            ]
            await self._store_memory(values)
        profile_updates = data.profile_updates
        if profile_updates and any([profile_updates.tech_stack, profile_updates.interests,
                                      profile_updates.experience, profile_updates.preferences]):
            await self._update_profile(user_id, profile_updates)

    async def _store_memory(self, values):
        await db.execute_many(
            """
            INSERT INTO user_memory
                (memory_id, user_id, content, importance, 
                 source_conversation_id, create_time, update_time)
            VALUES 
                (:mid,:uid,:content,:imp,:src_conv,:now,:now)
            """,
            values,
        )
        # ─── ES 批量写入 ───
        try:
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
                    },
                }
                for r, vec in zip(values, vectors)
            ]
            ok,errors = await async_bulk(self._es.client,actions,raise_on_error=False)
            user_id = values[0]["uid"]
            if errors:
                log.warning("记忆写入 ES 部分失败: %s", errors)
            else:
                log.info("批量写入 ES: user=%s, count=%d", user_id, ok)

        except Exception as e:
            log.warning("记忆批量写入 ES 失败: %s", e)

        log.info("存储记忆: user=%s, count=%d", user_id, len(values))
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
        log.info("更新用户画像: user=%s, updates=%s", user_id, updates)
        profile = await self._get_profile(user_id)
        if profile is None:
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
                }
            )
            #更新用户画像小结
        await self._regenerate_summary(user_id)

    async def _regenerate_summary(self, user_id):
        """用 LLM 重新生成用户画像摘要"""
        log.info("重新生成用户画像摘要: user=%s", user_id)
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
        # 1. 衰减低访问记忆的重要性
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

        # 2. 找出要删除的记忆 ID
        to_delete = await db.fetch_all(
            "SELECT memory_id FROM user_memory WHERE user_id = :uid AND importance < 0.1",
            {"uid": user_id},
        )
        delete_ids = [row["memory_id"] for row in to_delete]

        # 3. 删除 MySQL
        if delete_ids:
            placeholders = ", ".join(f":id{i}" for i in range(len(delete_ids)))
            params = {f"id{i}": mid for i, mid in enumerate(delete_ids)}
            await db.execute(
                f"DELETE FROM user_memory WHERE memory_id IN ({placeholders})",
                params,
            )

            # 4. 同步删除 ES
            try:
                actions = [
                    {"_op_type": "delete", "_index": "user_memories", "_id": str(mid)}
                    for mid in delete_ids
                ]
                await async_bulk(self._es.client, actions, raise_on_error=False)
                log.info("记忆遗忘同步删除 ES: user=%s, count=%d", user_id, len(delete_ids))
            except Exception as e:
                log.warning("遗忘同步删除 ES 失败: %s", e)

        log.info("记忆衰减完成: user=%s, factor=%.2f, deleted=%d", user_id, decay_factor, len(delete_ids))
    #──────────── 获取用户画像 ──────────────
    async def recall(self,user_id: int,query: str,top_k:int=5)->str:
        """
                根据当前问题召回相关记忆

                返回格式化字符串，直接注入给 LLM 作为上下文
                """
        log.info("用户画像查询%d", user_id)
        # 1. ES 向量检索，只拿候选 memory_id
        candidates = await self._search_memories(user_id, query, top_k)

        # 2. 获取用户画像
        profile = await self._get_profile(user_id)
        profile_summary = profile.get("summary", "暂无用户画像") if profile else "新用户，暂无画像"

        if not candidates and profile_summary in ("暂无用户画像", "新用户，暂无画像"):
            return ""  # 无有效信息，不注入无用的 system prompt

        # 3. 拿候选 ID 去 MySQL 查最新数据
        relevant_memories = []
        if candidates:
            memory_ids = [c["memory_id"] for c in candidates]
            placeholders = ", ".join(f":id{i}" for i in range(len(memory_ids)))
            params = {f"id{i}": mid for i, mid in enumerate(memory_ids)}

            rows = await db.fetch_all(
                f"SELECT memory_id, content, importance, access_count "
                f"FROM user_memory WHERE memory_id IN ({placeholders})",
                params,
            )
            # 如果 MySQL 里已经不存在（被 decay 删了），就自然过滤掉了
            relevant_memories = [dict(r._mapping) for r in rows]

            # 4. 更新访问计数（只对 MySQL 里还存在的）
            if relevant_memories:
                alive_ids = [m["memory_id"] for m in relevant_memories]
                alive_ph = ", ".join(f":aid{i}" for i in range(len(alive_ids)))
                alive_params = {f"aid{i}": mid for i, mid in enumerate(alive_ids)}
                await db.execute(
                    f"UPDATE user_memory SET access_count = access_count + 1 "
                    f"WHERE memory_id IN ({alive_ph})",
                    alive_params,
                )

        # 5. 格式化输出
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
                results.append({
                    "memory_id": hit["_source"]["memory_id"],
                    "score": hit["_score"],
                })
            return results
        except Exception as e:
            log.warning("记忆检索失败: %s", e)
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
    def _extract_cooldown_key(self,conversation_id:int):
        return f"py_mem_extract:{conversation_id}"
    async def in_extract_cooldown(self,conversation_id:int)->bool:
        """判断是否在冷却中"""
        data = await self._redis.get(self._extract_cooldown_key(conversation_id))
        return bool(data)
    async def mark_extract_scheduled(self,conversation_id:int):
        await self._redis.set(
            self._extract_cooldown_key(conversation_id),
            "1",
            ex=EXTRACT_COOLDOWN_SECONDS,
        )
    def _find_last_user_text(self,messages:list[dict])->str:
        for msg in messages:
            if msg["role"] == "user":
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
    ) -> bool:
        if interrupted:
            return False
        if not assistant_text.strip():
            return False

        last_user_text = self._find_last_user_text(messages)
        if self.is_low_value_round(last_user_text, assistant_text):
            return False

        if await self.in_extract_cooldown(conversation_id):
            return False

        if self.has_profile_signal(last_user_text):
            return True

        user_turn_count = self._count_user_turns(messages)
        if user_turn_count > 0 and user_turn_count % EXTRACT_INTERVAL_TURNS == 0:
            return True

        return False
# ─── 全局单例 ───
memory_service = MemoryService()