"""
查询改写服务
对应 Java: QueryRewriteService.java
"""
import json
import logging
from typing import Optional, Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings, get_llm
# 用户输入llm解析条件
class QueryFilters(BaseModel):
    """LLM 从用户 query 中抽取的自然语言过滤条件，不包含数据库 ID"""
    tags: list[str] = Field(default_factory=list, description="技术标签关键词，如 Spring、Vue")
    time_range: Optional[Literal["today", "week", "month", "year", "all"]] = Field(
        default=None, description="时间范围，用户显式提到才填"
    )
    category_names: list[str] = Field(
        default_factory=list,
        description="用户话里出现的分类名，如 后端、前端、面试；不要输出 category_id"
    )
    author_name: Optional[str] = Field(
        default=None,
        description="用户话里出现的作者昵称；不要输出 user_id"
    )
# 后端查库解析结果
class ResolvedFilters(BaseModel):
    """后端查库解析后的可执行过滤条件，只有 resolver 能生成 ID"""
    tags: list[str] = Field(default_factory=list)
    time_range: Optional[Literal["today", "week", "month", "year", "all"]] = None
    category_ids: list[int] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)
    soft_terms: list[str] = Field(default_factory=list, description="未可靠解析为 ID 的分类名/作者名等软约束")
class RewriteResult(BaseModel):
    semantic_queries: list[str] = Field(description="3 条语义扩展查询")
    keywords: list[str] = Field(description="3-4 个关键词（用于 BM25）")
    filters: QueryFilters = Field(default_factory=QueryFilters)
    search_mode: Literal["platform", "web", "hybrid"] = Field(
        default="hybrid",
        description="platform=只搜平台文章；web=优先联网；hybrid=平台+必要时联网"
    )
    need_web_search: bool = Field(default=False, description="涉及最新/实时/外部信息时为 true")

REWRITE_SYSTEM_PROMPT = """你是查询改写助手。根据用户问题和上下文，输出结构化检索参数。

【输出字段】
- semantic_queries：3 条语义扩展查询（自然语言）
- keywords：3-4 个关键词（精准短语）
- filters.tags：用户查询涉及的技术标签（如 Spring、Vue、Java）
- filters.time_range：仅当用户显式提到"最新/本周/今天/今年"等时间锚定词时填；否则 null
- filters.category_names：只填用户话里出现的分类名，不要猜 category_id
- filters.author_name：只填用户话里出现的作者昵称，不要猜 user_id
- search_mode：platform(只搜平台) / web(优先联网) / hybrid(平台+必要时联网)
- need_web_search：涉及实时/最新/外部信息=true，否则 false

【示例】
Q: "最近 Spring Boot 的新特性"
→ filters.time_range="month", filters.tags=["Spring Boot"], search_mode="hybrid", need_web_search=true

Q: "找几篇 Spring Boot 性能优化文章"
→ filters.tags=["Spring Boot"], search_mode="platform", need_web_search=false

Q: "找一下后端分类里小王写的 Redis 文章"
→ filters.category_names=["后端"], filters.author_name="小王", filters.tags=["Redis"], search_mode="platform"

Q: "RAG 是什么"
→ filters.tags=["RAG"], search_mode="hybrid", need_web_search=false
"""


class QueryRewriteService:
    def __init__(self):
        self.llm = get_llm()

    async def rewrite(self, query: str, history_messages: list[dict]) -> dict:
        """
        改写查询
        返回 dict，便于后续节点直接使用
        """
        history_text = self._build_history_text(history_messages)

        messages = [
            SystemMessage(content=REWRITE_SYSTEM_PROMPT),
            HumanMessage(content=f"用户问题：{query}\n\n最近历史消息：{history_text}"),
        ]

        try:
            resp = await self.llm.ainvoke(messages)
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            result = RewriteResult(**data)
            return {
                "semantic_queries": result.semantic_queries,
                "keywords": result.keywords,
            }
        except Exception as e:
            log.warning("查询改写失败，使用原始查询: %s", e)
            return {
                "semantic_queries": [query],
                "keywords": [query],
            }

    @staticmethod
    def _build_history_text(history_messages: list[dict]) -> str:
        if not history_messages:
            return "无"

        lines = []
        for msg in history_messages[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "无"
