"""
Search Worker 节点
对应 Java: SearchWorkerNode.java
"""
from datetime import datetime

from app.services import filter_resolver, retrieval_service
from app.services.logging_config import get_logger, truncate
from app.skills.registry import skill_registry

log = get_logger(__name__)

from app.config import settings
from app.clients.mysql_client import db
from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
from app.services.observability import trace_node
from app.services.query_rewrite import QueryRewriteService, QueryFilters
from app.services.reranker import RerankerService
from app.clients.es_client import EsVectorStore, EsComponent
from app.services.tool_registry import tool_registry
from app.tools.web_search import do_search
# 服务实例
query_rewrite_service = QueryRewriteService()
reranker_service = RerankerService()
es_vector_store = EsVectorStore()
es_component = EsComponent()
filter_resolver_instance = filter_resolver.FilterResolver()
retrieval_service_instance = retrieval_service.RetrievalService()


SEARCH_SYSTEM_PROMPT = """你是一个信息检索助手。

已通过平台 RAG 检索到参考资料，见下文。
如果参考资料不足以回答问题（如涉及实时信息、最新动态），请调用 web_search 工具补充联网数据。

【当前日期】{current_date}"""


def _build_cards_from_results(results: list[dict]) -> list[dict]:
    """从 ES 原始搜索结果构建前端卡片数据（旁路，不经过 LLM）"""
    cards = []
    for r in results:
        card = {
            "articleId": str(r.get("article_id", "")),
            "title": r.get("title", ""),
            "coverImage": r.get("cover_image") or r.get("cover", ""),
            "authorName": r.get("author_name", ""),
            "viewCount": int(r.get("view_count", 0) or 0),
            "likeCount": int(r.get("like_count", 0) or 0),
        }
        if card["articleId"]:
            cards.append(card)
    return cards


async def _enrich_cards_from_mysql(cards: list[dict]) -> list[dict]:
    """
    卡片元数据回查：article_vectors 索引只带 article_id/title，
    需要回 MySQL 补齐 cover/author/view/like 等卡片字段。
    对应 Java: RagService 里按 article_id 批量回查 MySQL 的逻辑。
    """
    if not cards:
        return cards

    # 收集需要补齐的 article_id（过滤无效 / web_ 等非真实 article 的卡片）
    article_ids = []
    for c in cards:
        aid = c.get("articleId")
        if not aid or not aid.isdigit():
            continue
        # 缺任一关键字段就补
        if not c.get("coverImage") or not c.get("authorName") \
                or not c.get("viewCount") or not c.get("likeCount"):
            article_ids.append(aid)

    if not article_ids:
        return cards

    placeholders = ", ".join(f":id{i}" for i in range(len(article_ids)))
    params = {f"id{i}": aid for i, aid in enumerate(article_ids)}

    try:
        rows = await db.fetch_all(
            f"""
            SELECT a.article_id, a.cover_image, a.view_count, a.like_count,
                   u.nick_name AS author_name
            FROM article_info a
            LEFT JOIN user_info u ON a.user_id = u.user_id
            WHERE a.article_id IN ({placeholders})
            """,
            params,
        )
    except Exception as e:
        log.warning("[search_worker] 卡片 MySQL 回查失败: %s", e)
        return cards

    meta = {str(r._mapping["article_id"]): dict(r._mapping) for r in rows}
    for c in cards:
        m = meta.get(c["articleId"])
        if not m:
            continue
        c["coverImage"] = c.get("coverImage") or m.get("cover_image") or ""
        c["authorName"] = c.get("authorName") or m.get("author_name") or ""
        c["viewCount"] = int(c.get("viewCount") or m.get("view_count") or 0)
        c["likeCount"] = int(c.get("likeCount") or m.get("like_count") or 0)
    return cards
@trace_node("search_worker")
async def search_worker_node(state: AgentState) -> dict:
    """
    搜索 Worker：两阶段检索（粗检索 + Reranker 精排）
    
    对应 Java: SearchWorkerNode.apply()
    """
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("search", state["user_message"])
    # 如果有反思反馈，注入到任务描述中
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"
    history_messages = state["history_messages"]
    # 动态拼接skill
    required_skills =  state.get("required_skills", [])
    system_prompt = SEARCH_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"
    
    log.info("[search_worker] 启动 | task=%r | required_skills=%s",
             (task_input or "")[:200], required_skills)

    # 1. Query Rewriting
    rewrite_result = await query_rewrite_service.rewrite(task_input, history_messages)
    log.info("[search_worker] 查询改写 | semantic=%s | keywords=%s",
             rewrite_result.get("semantic_queries"), rewrite_result.get("keywords"))
    #2. 自然语言 filter 解析为可执行 filter。LLM 不直接生成 category_id/user_id
    raw_filters: QueryFilters = rewrite_result["filters"]
    resolved_filters = await filter_resolver_instance.resolve(raw_filters)
    search_mode = rewrite_result.get("search_mode", "hybrid")
    need_web_search = rewrite_result.get("need_web_search", False)
    # 3. 粗检索：替换旧 execute_coarse_retrieval，改为 RRF 融合召回
    candidates = await retrieval_service_instance.hybrid_search(
        semantic_queries=rewrite_result["semantic_queries"],
        keywords=rewrite_result["keywords"] + resolved_filters.soft_terms,
        filters=resolved_filters,
        search_mode=search_mode,
        top_k=settings.COARSE_TOP_K,
    )
    log.info("[search_worker] 粗检索完成 | 候选数=%d", len(candidates))

    # 4. Reranker 精排。原有 fallback 逻辑保留
    if candidates:
        ranked = await reranker_service.rerank(task_input, candidates)
        log.info("[search_worker] 精排完成 | 排序后=%d | top3=%s",
                 len(ranked),
                 [{"title": d.get("title", "")[:40], "score": round(d.get("score", 0), 3)}
                  for d in ranked[:3]])
    else:
        ranked = []
        log.info("[search_worker] 粗检索无结果，跳过精排")
    # 5. 旁路卡片仍然从精排结果构建，不经过 LLM
    article_cards = _build_cards_from_results(ranked)
    # 回查 MySQL 补齐 cover/author/view/like（article_vectors 索引没这些字段）
    article_cards = await _enrich_cards_from_mysql(article_cards)

    # 6. 替换旧 build_rag_context：由 CitationBuilder 同时生成 citations + LLM context
    citations, rag_context = citation_builder_instance.build(ranked)
    if need_web_search:
        system_prompt += "\n\n若平台资料不足，请优先调用 web_search 补充最新信息。"

    # 7. tool agent 流程保留
    all_tools = tool_registry.get_all_tools()
    reply = await run_tool_agent(
        system_prompt=system_prompt.format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        ),
        user_input=f"任务：{task_input}\n\nRAG 参考资料：\n{rag_context}",
        tools=all_tools,
        max_rounds=2,
        tag="search_worker",
    )

    log.info("[search_worker] 完成 | 卡片数=%d | citation数=%d | reply_len=%d",
             len(article_cards), len(citations), len(reply or ""))

    return {
        "worker_results": [{
            "worker_name": "search",
            "result": reply,
        }],
        "article_cards": article_cards,
        "citations": [c.__dict__ for c in citations],
    }


async def execute_coarse_retrieval(rewrite_result: dict) -> list[dict]:
    """
    粗检索：多路召回
    对应 Java: SearchWorkerNode.executeCoarseRetrieval()
    """
    doc_map = {}  # 用于去重，类似 Java 的 LinkedHashMap
    
    # 1. 语义搜索（向量 KNN）
    for semantic_query in rewrite_result.get("semantic_queries", []):
        try:
            chunks = await es_vector_store.search(
                semantic_query,
                settings.COARSE_TOP_K,
                settings.COARSE_SIMILARITY_THRESHOLD
            )
            for chunk in chunks:
                key = f"{chunk['article_id']}_{chunk['chunk_index']}"
                if key not in doc_map:
                    doc_map[key] = chunk
        except Exception as e:
            log.warning("语义搜索失败: %s", e)
    
    # 2. 关键词搜索（平台文章）
    for keyword in rewrite_result.get("keywords", []):
        try:
            articles = await es_component.search(keyword, page_size=5)
            for article in articles:
                key = f"keyword_{article['article_id']}"
                if key not in doc_map:
                    doc_map[key] = {
                        "article_id": article["article_id"],
                        "title": article["title"],
                        "content": article.get("summary", ""),
                        "chunk_index": 0
                    }
        except Exception as e:
            log.warning("关键词搜索失败: %s", e)

    # 3. 联网搜索兜底（RAG 无结果时）
    if not doc_map:
        queries = rewrite_result.get("semantic_queries", []) or rewrite_result.get("keywords", [])
        if queries:
            try:
                web_results = await do_search(queries[0], size=5)
                for i, item in enumerate(web_results):
                    key = f"web_{i}"
                    doc_map[key] = {
                        "article_id": key,
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                        "chunk_index": i,
                        "score": 0.1,
                    }
            except Exception as e:
                log.warning("联网搜索失败: %s", e)

    return list(doc_map.values())


def build_rag_context(ranked_docs: list[dict]) -> str:
    """
    构建 RAG 上下文
    对应 Java: SearchWorkerNode.buildRagContext()
    """
    if not ranked_docs:
        return "未找到相关资料"
    
    context_parts = []
    for i, doc in enumerate(ranked_docs[:5]):
        title = doc.get("title", "无标题")
        content = doc.get("content", "")
        # 截断过长内容
        if len(content) > 500:
            content = content[:500] + "..."
        context_parts.append(f"【{i+1}. {title}】\n{content}")
    
    return "\n\n".join(context_parts)
