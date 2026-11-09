# RAG 系统深度优化方案（修订版）

> 2026-10-01 实现更新：已落地 HTML DOM 分块、`article_vectors` 同粒度 BM25/KNN、版本化 chunk_id RRF、MySQL 块版本校验和完整块上下文。当前代码与重建步骤以 [24-html-chunk-rag.md](24-html-chunk-rag.md) 为准。下文的双索引兼容、固定长度切块和 Parent/CRAG 等 Phase 描述保留为历史方案，不代表当前全部实现状态。

> 面向 `python-agent/app/graph/nodes/search_worker.py` + `python-agent/app/services/query_rewrite.py` + `python-agent/app/services/reranker.py` 的一揽子优化，按"**落地新技术、不造轮子、对论文有亮点**"排序。

> 2026-05-14 修订说明：本文档已按当前代码重新校准。当前线上入口是 Java `AgentService` 转发到 Python Agent；RAG 主流程在 `python-agent`，文章向量索引仍由 Java 侧 `ArticleVectorListener` / `DocumentChunkService` 写入。因此所有检索优化必须同时考虑 **Python 查询侧** 和 **Java 建索引侧** 的字段一致性。

## 0. 背景

### 0.1 现状拆解

```
用户 query
  │
  ▼
query_rewrite.py          │ semantic_queries + keywords（双路）
  │
  ▼
search_worker.py
  ├── EsVectorStore.search()           │ KNN + 热度混合分数
  ├── EsComponent.search()             │ multi_match（title + tags）
  └── do_search()                       │ 联网兜底
  │
  ▼  去重合并（LinkedHashMap 风格）
reranker.py               │ DashScope qwen3-vl-rerank API
  │
  ▼
build_rag_context         │ 截断 500 字 + 拼接 【i. 标题】内容
  │
  ▼
run_tool_agent            │ LLM + tools（平台内搜索 + web_search）
```

### 0.1.1 当前代码约束（必须先对齐）

- 当前 Java `AgentService` 已改为转发 Python `/chat`、`/chat/stream`，Java Graph 里的 `SearchWorkerNode` 不是主运行路径；本文档实现优先改 `python-agent`。
- `article_vectors` 索引由 Java 侧构建，当前字段主要是 `chunk_id/article_id/user_id/title/chunk_content/chunk_index/content_vector/source_type/create_time/tags/like_count/collect_count`。
- 文档中涉及 `category_id/publish_time/heading_path/parent_chunks` 的功能，必须先改 Java 入库实体、mapping 和历史重建任务，否则 Python 查询侧 filter 会查不到字段。`category_id/user_id` 不能由 LLM 直接生成，必须由后端查库解析。
- 当前 Python 粗检索是双索引：KNN 查 `article_vectors`，关键词查 `article`。因此 Phase 1 优先做**手写 RRF 融合双索引结果**；ES 原生 RRF 只能作为后续优化或在 BM25 也迁到 `article_vectors` 后启用。
- 当前 SSE 事件在 `python-agent/app/main.py` 统一下发，`search_worker` 不能直接 `yield`。Citation 应先写入 graph state，再由 `main.py` 像 `__ARTICLES__` 一样发送 `__CITATIONS__`。

### 0.2 已经做对的事

- ✅ Query rewriting（双路输出）
- ✅ Reranker（API 形式，无需本地 GPU）
- ✅ 多路召回 + 联网兜底
- ✅ 旁路卡片构建（检索结果直送前端，不经过 LLM）
- ✅ MySQL 回查补齐卡片元数据

### 0.3 核心短板（按优先级）

| 编号 | 短板 | 影响 |
| --- | --- | --- |
| **P0** | 召回融合只是去重追加，未用 RRF | 多路结果只按插入顺序保留，缺少稳定融合 |
| **P0** | metadata filter 字段不完整 | `user_id/tags` 已有；`category_id/publish_time` 还要补齐，否则时间/分类过滤无法真正生效 |
| **P0** | 无 **citation**，回答不可溯源 | 用户体验差、论文弱点 |
| **P1** | chunk 是固定长度切，**丢结构** | markdown 标题结构被切断 |
| **P1** | 无 **parent document** 还原 | 小 chunk 给 LLM 上下文不足 |
| **P1** | 无 **评测** | 改好改坏说不清 |
| **P2** | 无 **检索结果缓存** | 热点 query 重复计算 |
| **P2** | 无 **CRAG 式检索后校验** | 噪音 chunk 污染上下文 |

## 1. 架构目标

```
用户 query
  │
  ▼
query_rewrite.py  ┌──────────────────────────────┐
                  │  输出：                       │
                  │  - semantic_queries          │
                  │  - keywords                  │
                  │  - filters（分类/时间/作者） │── 新增
                  │  - search_mode / need_web_search │── 新增
                  └──────────────────────────────┘
  │
  ▼
retrieval_service.py  ◀─── 【新模块】抽离 search_worker 里的检索逻辑
  │
  ├── Manual RRF Retriever      │ 首期手写 RRF，兼容当前双索引
  │     ├── article_vectors KNN │ 语义路
  │     └── article BM25        │ 关键词路
  │
  ├── ES Native RRF Retriever   │ 后续可选：BM25 也迁到 article_vectors 后启用
  │     ▼
  │   合并后的 ranked_chunks
  │
  ▼
CRAG Grader（可选开关）        │ 每个 chunk 让小模型判定相关性
  │   ↘ 过滤掉 Incorrect
  ▼
Parent Expander                │ chunk → parent doc 窗口扩展
  │
  ▼
Reranker（qwen3-vl-rerank）    │ 保留，精排
  │
  ▼
Citation Builder               │ 给每段参考资料编号 [1] [2]
  │
  ▼
LLM（强制引用 prompt）         │ 输出带 [i] 标注的回答
  │
  ▼
Graph State 写入 citations     │ search_worker 不直接发 SSE
  │
  ▼
main.py 透传 __CITATIONS__      │ 前端把 [i] 渲染成可跳转卡片
```

## 2. 落地方案（Phase 划分）

> Phase 1/2 是毕业论文必做项，Phase 3 是"锦上添花 + 论文加分项"。

- **Phase 1（核心召回重构）**：手写 RRF 融合 + Metadata Filter 字段补齐 + Citation
- **Phase 2（文档结构优化）**：Semantic Chunking + Parent Document Retriever
- **Phase 3（高级增强）**：CRAG Grader + Retrieval Cache + Eval Harness

---

# Phase 1：核心召回重构

## 1.1 Query Rewriting v2：补 filters + search_mode

**目标**：让 `query_rewrite` 在 `search_worker` 内部一次性产出检索参数。后续的 `retrieval_service`、`reranker`、`citation_builder`、`web fallback` 只消费这些结构化字段，不再各自重新猜“要不要联网 / 要不要加时间过滤 / 用哪些关键词”。

过滤条件分两类：

- **硬过滤**：确定性高，直接下推 ES，例如明确时间范围、已存在的标签、resolver 唯一命中的分类/作者 ID。
- **软约束**：不稳定或查库不确定，例如用户口语化分类名、模糊作者名。软约束不下推 ES，只加入关键词扩展、RRF 候选文本或 rerank 输入。

注意：全局的“要不要进入 search_worker”已经由 Planner/Dispatcher 判断。这里不再承担 `generate/chitchat` 这类全局路由职责。

### 1.1.1 Schema 变更

```python
# python-agent/app/services/query_rewrite.py

from typing import Optional, Literal
from pydantic import BaseModel, Field


class QueryFilters(BaseModel):
    """LLM 只抽自然语言条件，不碰数据库 ID"""
    tags: list[str] = Field(default_factory=list, description="技术标签关键词，如 Spring、Vue")
    time_range: Optional[Literal["today", "week", "month", "year", "all"]] = Field(
        default=None, description="时间范围；只有用户显式提到时才填"
    )
    category_names: list[str] = Field(
        default_factory=list,
        description="分类名列表；未提及就保持空列表，不用 Optional",
    )
    author_name: Optional[str] = Field(
        default=None,
        description="作者昵称；未提及就为 None",
    )


class ResolvedFilters(BaseModel):
    """后端查库后的可执行过滤条件，只有 resolver 能生成 ID"""
    tags: list[str] = Field(default_factory=list)
    time_range: Optional[Literal["today", "week", "month", "year", "all"]] = None
    category_ids: list[int] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)
    soft_terms: list[str] = Field(
        default_factory=list,
        description="没能稳定解析成 ID 的分类名/作者名/未命中的标签",
    )


class RewriteResult(BaseModel):
    semantic_queries: list[str] = Field(default_factory=list, description="3 条语义扩展查询")
    keywords: list[str] = Field(default_factory=list, description="3-4 个关键词，用于 BM25")
    filters: QueryFilters = Field(default_factory=QueryFilters)
    search_mode: Literal["platform", "web", "hybrid"] = Field(
        default="hybrid",
        description="platform=只搜平台文章；web=优先联网；hybrid=平台优先，必要时联网",
    )
    need_web_search: bool = Field(default=False, description="涉及最新/实时/外部信息时为 true")
```

字段语义要分开看：

- `QueryFilters` 是 LLM 的原始抽取结果，允许“有词无 ID”
- `ResolvedFilters` 是后端解析后的执行结果，只把可确认的 ID 下推 ES
- `category_names` 不用 `Optional[list[str]]`，因为“没提到”用空列表 `[]` 就够了
- `search_mode` 只影响 `search_worker` 内部召回路径，后续节点不再重新理解 query 意图

### 1.1.2 Prompt 更新

```python
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
```

执行侧注意：

- LLM 只负责抽取 filter 候选，不能假装知道 `category_id` 或 `user_id`。分类名/作者名到 ID 的转换应走 MySQL 或缓存字典。
- 在 `article_vectors` 未补 `category_id/publish_time` 前，只启用 `tags` 和时间 fallback；不要把不存在的字段塞进 ES filter。

### 1.1.3 FilterResolver：自然语言 filter → 数据库 ID

`query_rewrite` 输出的 `category_names/author_name` 不能直接下推 ES，需要先解析。这里的 `FilterResolver` 不是“神秘外部依赖”，就是一个同文件内的私有 helper 集合，`__init__` 只负责拿到 `python-agent/app/clients/mysql_client.py` 导出的 `db` 单例：

```python
# python-agent/app/services/filter_resolver.py
from app.clients.mysql_client import db
from app.services.query_rewrite import QueryFilters, ResolvedFilters


class FilterResolver:
    def __init__(self):
        self._db = db  # mysql_client.py 导出的 Database 单例

    async def resolve(self, filters: QueryFilters) -> ResolvedFilters:
        resolved_tags, tag_soft_terms = await self._resolve_tags(filters.tags)
        category_ids, category_soft_terms = await self._find_category_ids(filters.category_names)
        author_ids, author_soft_terms = await self._find_author_ids(filters.author_name)

        soft_terms = [*tag_soft_terms, *category_soft_terms, *author_soft_terms]
        return ResolvedFilters(
            tags=resolved_tags,
            time_range=filters.time_range,
            category_ids=category_ids,
            author_ids=author_ids,
            soft_terms=soft_terms,
        )

    async def _resolve_tags(self, tags: list[str]) -> tuple[list[str], list[str]]:
        """把用户词汇规范化成 article_tag.tag_name 里真实存在的 canonical tag。"""
        if not tags:
            return [], []

        placeholders, params = self._in_params("tag", tags)
        rows = await self._db.fetch_all(
            f"""
            SELECT tag_name
            FROM article_tag
            WHERE tag_name IN ({placeholders})
            """,
            params,
        )
        matched = {str(r["tag_name"]) for r in rows}
        canonical = [tag for tag in tags if tag in matched]
        unmatched = [tag for tag in tags if tag not in matched]
        return canonical, unmatched

    async def _find_category_ids(self, category_names: list[str]) -> tuple[list[int], list[str]]:
        """只接受能稳定解析成唯一 category_id 的分类名。"""
        if not category_names:
            return [], []

        placeholders, params = self._in_params("category", category_names)
        rows = await self._db.fetch_all(
            f"""
            SELECT category_id, category_name
            FROM article_category
            WHERE category_name IN ({placeholders})
            """,
            params,
        )
        matched = {str(r["category_name"]): int(r["category_id"]) for r in rows}
        ids = [matched[name] for name in category_names if name in matched]
        soft_terms = [name for name in category_names if name not in matched]
        return ids, soft_terms

    async def _find_author_ids(self, author_name: str | None) -> tuple[list[int], list[str]]:
        """昵称必须唯一命中；空结果或重名都降级成 soft_terms。"""
        if not author_name:
            return [], []

        rows = await self._db.fetch_all(
            """
            SELECT user_id, nick_name
            FROM user_info
            WHERE nick_name = :author_name
            """,
            {"author_name": author_name},
        )
        if len(rows) != 1:
            return [], [author_name]
        return [int(rows[0]["user_id"])], []

    @staticmethod
    def _in_params(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
        placeholders = ", ".join(f":{prefix}{i}" for i in range(len(values)))
        params = {f"{prefix}{i}": value for i, value in enumerate(values)}
        return placeholders, params
```

解析规则：

- 用户不会说 `category_id=3`，只会说“后端分类”“面试分类”“小王的文章”；LLM 只抽 `category_names/author_name`
- `category_names` 是自然语言候选，不是稳定输入。用户可能说“后端”“Java 后台”“服务端”，数据库分类可能叫“后端开发”
- 分类名只在能稳定解析成唯一 `category_id` 时才进入硬过滤；查不到或匹配不唯一时，保留到 `soft_terms`
- 作者昵称同理，只有唯一命中 `user_info.nick_name` 时才进入 `author_ids`；同名/歧义都降级为 `soft_terms`
- `tags` 不是直接塞给 ES，而是先和 `article_tag.tag_name` 做 canonical match；匹配不上的 tag 也进入 `soft_terms`，交给关键词召回或 rerank

### 1.1.4 调用方改造

`search_worker.py` 中的 `rewrite_result` 解包：

```python
rewrite_result = await query_rewrite_service.rewrite(task_input, history_messages)
raw_filters: QueryFilters = rewrite_result["filters"]
resolved_filters = await filter_resolver_instance.resolve(raw_filters)
search_mode = rewrite_result.get("search_mode", "hybrid")
need_web_search = rewrite_result.get("need_web_search", False)

candidates = await retrieval_service_instance.hybrid_search(
    semantic_queries=rewrite_result["semantic_queries"],
    keywords=rewrite_result["keywords"] + resolved_filters.soft_terms,
    filters=resolved_filters,
    search_mode=search_mode,
    top_k=settings.COARSE_TOP_K,
)
```

补一句：`search_mode` 只在 `search_worker` 内部决定平台检索 / 联网兜底的顺序，后面的 `reranker`、`citation_builder`、`run_tool_agent` 都不再重新理解 query 意图，只消费 `ranked_chunks` 和 `citations` 这些结果态。

---

## 1.2 ES RRF 融合替代线性加权

> 修订：当前首期不建议直接上 ES 原生 RRF。原因是现有粗检索跨两个索引：`article_vectors` 做 KNN，`article` 做关键词检索；ES 原生 RRF 更适合在同一次 search 中融合多个 retriever。首期应先在 Python 层手写 RRF，兼容双索引；等 `article_vectors` 补齐 BM25 所需字段后，再切到 ES 原生 RRF。

### 1.2.1 为什么 RRF

- 旧向量路：`score = vector × 0.7 + popularity × 0.3`
  - 向量 cosine 是 0~1，BM25 无上界，根本没法直接加
  - 不同 query 下最优权重不同，必须死调
- 当前 `search_worker`：语义结果和关键词结果只是按插入顺序去重合并，关键词召回没有参与可解释的融合排序
- RRF：只看**排名**不看分数，公式 $score_{rrf}(d) = \sum_i \frac{1}{k + rank_i(d)}$
  - 量纲无关、参数只有一个 `k`（经验值 60）
  - 首期可以手写实现，兼容 `article_vectors + article` 双索引
  - ES 8.8+ 原生支持 `retriever: { rrf: [...] }`，可作为后续优化

### 1.2.2 ES 新索引 mapping（兼容旧 chunk）

旧 `article_vectors` 索引的 mapping 基本可用，但需要增加两类字段以配合 Phase 1 filter 和 Phase 2 parent expand。

当前已存在字段：

```json
{
  "chunk_id": "keyword",
  "article_id": "keyword",
  "user_id": "long",
  "title": "text",
  "chunk_content": "text",
  "chunk_index": "integer",
  "content_vector": "dense_vector",
  "source_type": "keyword",
  "create_time": "date",
  "tags": "keyword",
  "like_count": "integer",
  "collect_count": "integer"
}
```

需要补齐字段：

```json
{
  "properties": {
    "chunk_id":        { "type": "keyword" },
    "article_id":      { "type": "keyword" },
    "user_id":         { "type": "long" },
    "title":           { "type": "text", "analyzer": "ik_smart" },
    "chunk_content":   { "type": "text", "analyzer": "ik_max_word" },
    "chunk_index":     { "type": "integer" },

    "content_vector":  { "type": "dense_vector", "dims": 2048, "index": true, "similarity": "cosine" },

    "category_id":     { "type": "long" },
    "tags":            { "type": "keyword" },
    "publish_time":    { "type": "date" },
    "create_time":     { "type": "date" },

    "heading_path":    { "type": "keyword" },
    "parent_chunks":   { "type": "keyword" },

    "like_count":      { "type": "integer" },
    "collect_count":   { "type": "integer" }
  }
}
```

落地要求：

- `category_id/publish_time` 从 `Article` 写入 `DocumentChunk`，再进入 `article_vectors`。
- 作者过滤用 `user_id`，由 `FilterResolver` 根据 `author_name` 查 `user_info` 得到；不建议把 `author_name` 冗余进向量索引。如果确实要支持昵称搜索，需要考虑用户改名后的 ES 数据同步。
- 时间过滤首期可以用 `publish_time`；如果历史数据没有该字段，可临时 fallback 到 `create_time`。
- `heading_path/parent_chunks` 由 Phase 2 的语义分块生成；Phase 1 可以先留空。

### 1.2.3 新检索层：`retrieval_service.py`

把 `search_worker.py` 里的 `execute_coarse_retrieval()` 抽出来，单独成服务，后续 CRAG / Eval 都用它。

```python
# python-agent/app/services/retrieval_service.py
from datetime import datetime, timedelta

from app.clients.es_client import EsVectorStore, EsComponent
from app.services.query_rewrite import ResolvedFilters


class RetrievalService:
    K_RRF = 60

    def __init__(self):
        self._vector_store = EsVectorStore()
        self._article_search = EsComponent()

    async def hybrid_search(
        self,
        semantic_queries: list[str],
        keywords: list[str],
        filters: ResolvedFilters,
        search_mode: str = "hybrid",
        top_k: int = 20,
    ) -> list[dict]:
        """
        首期实现：手写 RRF 融合当前双索引结果。
        - semantic_queries -> article_vectors KNN
        - keywords -> article BM25
        """
        ranked_lists: list[list[dict]] = []

        vector_filter = self._build_vector_filter(filters)
        if search_mode in ("platform", "hybrid"):
            expanded_keywords = keywords + filters.soft_terms
            for q in semantic_queries:
                hits = await self._vector_store.search(
                    q,
                    top_k=top_k,
                    threshold=0.0,
                    filters=vector_filter,
                )
                ranked_lists.append([self._normalize_vector_hit(h) for h in hits])

            for kw in expanded_keywords:
                hits = await self._article_search.search(
                    kw,
                    page_size=top_k,
                    filters=self._build_article_filter(filters),
                )
                ranked_lists.append([self._normalize_article_hit(h) for h in hits])

        return self._rrf_merge(ranked_lists, top_k=top_k)

    def _build_vector_filter(self, filters: ResolvedFilters) -> dict:
        """只生成 article_vectors 已存在或已确认补齐的字段。"""
        clauses = []
        if filters.tags:
            clauses.append({"terms": {"tags": filters.tags}})
        if filters.category_ids:
            clauses.append({"terms": {"category_id": filters.category_ids}})
        if filters.author_ids:
            clauses.append({"terms": {"user_id": filters.author_ids}})
        if filters.time_range and filters.time_range != "all":
            clauses.append({"range": {"publish_time": {"gte": self._since(filters.time_range)}}})
        return {"bool": {"filter": clauses}} if clauses else {}

    def _build_article_filter(self, filters: ResolvedFilters) -> dict:
        """article 索引用 camelCase 字段。"""
        clauses = []
        if filters.category_ids:
            clauses.append({"terms": {"categoryId": filters.category_ids}})
        if filters.author_ids:
            clauses.append({"terms": {"userId": filters.author_ids}})
        if filters.time_range and filters.time_range != "all":
            clauses.append({"range": {"publishTime": {"gte": self._since(filters.time_range)}}})
        return {"bool": {"filter": clauses}} if clauses else {}

    @staticmethod
    def _since(time_range: str) -> str:
        delta_map = {
            "today": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
            "year": timedelta(days=365),
        }
        return (datetime.now() - delta_map[time_range]).isoformat()

    @staticmethod
    def _normalize_vector_hit(hit: dict) -> dict:
        return {
            **hit,
            "doc_key": f"{hit.get('article_id')}_{hit.get('chunk_index', 0)}",
            "source": "vector",
        }

    @staticmethod
    def _normalize_article_hit(hit: dict) -> dict:
        return {
            "article_id": hit.get("article_id"),
            "title": hit.get("title", ""),
            "content": hit.get("summary", ""),
            "chunk_index": 0,
            "cover_image": hit.get("cover_image", ""),
            "view_count": hit.get("view_count", 0),
            "like_count": hit.get("like_count", 0),
            "user_id": hit.get("user_id"),
            "doc_key": f"article_{hit.get('article_id')}",
            "source": "keyword",
        }

    def _rrf_merge(self, ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
        merged: dict[str, dict] = {}
        for docs in ranked_lists:
            for rank, doc in enumerate(docs, start=1):
                key = doc.get("doc_key") or str(doc.get("article_id"))
                item = merged.setdefault(key, {"doc": doc, "score": 0.0})
                item["score"] += 1.0 / (self.K_RRF + rank)

        out = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        result = []
        for item in out[:top_k]:
            doc = dict(item["doc"])
            doc["score"] = item["score"]
            doc["rrf_score"] = item["score"]
            result.append(doc)
        return result
```

> 注意：上面需要同步改 `EsVectorStore.search()` 和 `EsComponent.search()`，支持可选 `filters` 参数。若暂时不改底层 client，也可以先在 Python 内存中过滤，但数据量变大后必须下推到 ES。

### 1.2.3.1 ES 原生 RRF 后续版本

当 `article_vectors` 中已经包含 `title/chunk_content/tags/category_id/publish_time/user_id`，并且关键词路也迁到 `article_vectors` 后，再启用 ES 原生 RRF。不要在当前双索引状态下强行套原生 RRF。

### 1.2.4 search_worker 改造

这一段不是重写整个 `search_worker_node`。现有逻辑里的取消检查、反思反馈、skill 动态拼接、日志、卡片回查、tool agent 调用都要保留；只把“`execute_coarse_retrieval()` 粗检索 + `build_rag_context()`”替换成“filter resolve + RRF retrieval + citation context”。

```python
# python-agent/app/graph/nodes/search_worker.py
from datetime import datetime

from app.config import settings
from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
from app.services.logging_config import get_logger
from app.services.observability import trace_node
from app.services.citation_builder import CitationBuilder
from app.services.filter_resolver import FilterResolver
from app.services.query_rewrite import QueryRewriteService
from app.services.reranker import RerankerService
from app.services.retrieval_service import RetrievalService
from app.services.tool_registry import tool_registry
from app.skills.registry import skill_registry

log = get_logger(__name__)

query_rewrite_service = QueryRewriteService()
reranker_service = RerankerService()
retrieval_service_instance = RetrievalService()
filter_resolver_instance = FilterResolver()
citation_builder_instance = CitationBuilder()

@trace_node("search_worker")
async def search_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("search", state["user_message"])

    # 保留原有反思反馈注入，不能因为改 RAG 检索而删掉
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"

    history_messages = state["history_messages"]

    # 保留原有 skill 动态拼接
    required_skills = state.get("required_skills", [])
    system_prompt = SEARCH_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"

    log.info("[search_worker] 启动 | task=%r | required_skills=%s",
             (task_input or "")[:200], required_skills)

    # 1. Query Rewriting
    rewrite_result = await query_rewrite_service.rewrite(task_input, history_messages)
    log.info("[search_worker] 查询改写 | semantic=%s | keywords=%s | mode=%s",
             rewrite_result.get("semantic_queries"),
             rewrite_result.get("keywords"),
             rewrite_result.get("search_mode"))

    # 2. 自然语言 filter 解析为可执行 filter。LLM 不直接生成 category_id/user_id
    resolved_filters = await filter_resolver_instance.resolve(rewrite_result["filters"])
    need_web_search = rewrite_result.get("need_web_search", False)

    # 3. 粗检索：替换旧 execute_coarse_retrieval，改为 RRF 融合召回
    candidates = await retrieval_service_instance.hybrid_search(
        semantic_queries=rewrite_result["semantic_queries"],
        keywords=rewrite_result["keywords"] + resolved_filters.soft_terms,
        filters=resolved_filters,
        search_mode=rewrite_result.get("search_mode", "hybrid"),
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
```

### 1.2.5 论文章节点

> "多路召回的分数融合方法对比：线性加权 vs. RRF" —— 用 Phase 3 的 eval harness 跑一次 A/B 直接出图。

---

## 1.3 引用（Citation）机制

### 1.3.1 数据流

```
reranker 输出 ranked_chunks
  │
  ▼
CitationBuilder（新增）
  ├── 为每个 chunk 分配 citation_id = [1]..[N]
  └── 构建 LLM-facing 上下文 + 前端 citations payload
  │
  ▼
run_tool_agent (强制引用 prompt)
  ├── LLM 输出：含 [1] [2] 标注的回答
  │
  ▼
Graph State：
  ├── worker_results
  ├── article_cards
  └── citations
  │
  ▼
main.py SSE 事件：
  ├── synthesizer 文本流（含 [1] 原样透传）
  ├── __ARTICLES__:[{articleId, title, coverImage, authorName}]
  └── __CITATIONS__:[{id, source, articleId, title, url, coverImage, chunkContent}]
  │
  ▼
前端：
  ├── marked 渲染文本，拦截 [n] 为可点击元素
  └── 点击 [n] → 弹出 citations[n-1] 卡片/跳转文章
```

### 1.3.2 CitationBuilder

```python
# python-agent/app/services/citation_builder.py
from dataclasses import dataclass


@dataclass
class Citation:
    id: int           # 1-based
    source: str       # platform | web
    article_id: str
    title: str
    url: str
    cover_image: str
    chunk_snippet: str    # 给前端悬浮预览用
    heading_path: list[str]


class CitationBuilder:
    MAX_CITATIONS = 8
    SNIPPET_LEN = 200

    def build(self, ranked_chunks: list[dict]) -> tuple[list[Citation], str]:
        """
        :return: (前端用 citations, 注入给 LLM 的 rag_context 字符串)
        """
        citations: list[Citation] = []
        ctx_parts: list[str] = []

        for i, c in enumerate(ranked_chunks[: self.MAX_CITATIONS], start=1):
            snippet = (c.get("content") or "")[: self.SNIPPET_LEN]
            heading = " > ".join(c.get("heading_path", []))
            header = c["title"]
            if heading:
                header = f"{header} › {heading}"

            ctx_parts.append(f"[{i}] {header}\n{snippet}")

            citations.append(Citation(
                id=i,
                source=c.get("source", "platform"),
                article_id=str(c["article_id"]),
                title=c.get("title", ""),
                url=c.get("url", ""),
                cover_image=c.get("cover_image", ""),
                chunk_snippet=snippet,
                heading_path=c.get("heading_path", []),
            ))

        return citations, "\n\n".join(ctx_parts)
```

### 1.3.3 强制引用 Prompt

改写 `SEARCH_SYSTEM_PROMPT`：

```python
SEARCH_SYSTEM_PROMPT = """你是一个信息检索助手。

【参考资料格式】
参考资料以 `[编号] 标题\n内容` 形式给出，你必须：
1. 仅基于参考资料作答。无法从资料中得到答案时，明确说"资料中未提及"，不要编造
2. 每一个事实性陈述后必须标注来源编号，形如 `[1]` 或 `[2][3]`
3. 标注放在该句号之前，例如："Spring Boot 3 要求 Java 17 及以上[2]。"
4. 不要在回答开头罗列来源列表，也不要在结尾生成参考文献章节（前端会自动渲染）

【当前日期】{current_date}
"""
```

如果启用了 `web_search` 兜底，联网结果也必须进入 `CitationBuilder`，例如用 `source="web"`、`url`、`snippet` 生成同样的 `[i]` 引用。否则 prompt 要求“每句带引用”但 web 结果没有 citation payload，前端会渲染出无法跳转的空引用。

### 1.3.4 State + SSE 下发

是的，这里要给 `AgentState` 新增字段。`search_worker` 不直接 `yield` SSE，而是像 `article_cards` 一样把 citations 返回到 graph state，最后由 `main.py` 统一下发。

先改 `python-agent/app/graph/state.py`：

```python
class AgentState(TypedDict):
    # ...

    # 引用来源（chunk/web 结果），前端用来把回答中的 [n] 渲染成可点击 citation
    citations: Annotated[list[dict], add]
```

再改 `/chat/stream` 的 `initial_state`，把新增字段初始化出来；当前代码里 `required_skills/article_cards/needs_retry/retry_count/reflection_feedback` 也应该一起补齐，避免状态字段缺省：

```python
initial_state: AgentState = {
    "user_id": request.user_id,
    "user_message": processed_message,
    "history_messages": context,
    "active_workers": [],
    "task_descriptions": {},
    "required_skills": [],
    "worker_results": [],
    "article_cards": [],
    "citations": [],
    "final_reply": "",
    "cancelled": False,
    "needs_retry": False,
    "retry_count": 0,
    "reflection_feedback": "",
    "draft_article_id": None,
}
```

然后 `search_worker` 返回 citations：

```python
# python-agent/app/graph/nodes/search_worker.py
citations, rag_context = citation_builder_instance.build(ranked)

return {
    "worker_results": [{
        "worker_name": "search",
        "result": reply,
    }],
    "article_cards": article_cards,
    "citations": [c.__dict__ for c in citations],
}
```

然后在 `python-agent/app/main.py` 的 `/chat/stream` 末尾，和 `__ARTICLES__` 同一层读取最终 state 并下发：

```python
final_state = await graph.aget_state(config)
citations = final_state.values.get("citations", []) if final_state else []

if citations:
    yield _sse(f"__CITATIONS__:{json.dumps(citations, ensure_ascii=False)}")
```

`/chat/resume/stream` 如果也可能恢复到 `search_worker`，同样要在流结束处读取 `citations` 并下发。否则普通流有 citation，恢复流没有 citation，前端行为会不一致。

前端在 `AiChat.vue streamChat` 里加一路解析：

```ts
if (data.startsWith('__CITATIONS__:')) {
  try {
    const arr = JSON.parse(data.substring(14).trim())
    messages.value[aiMsgIndex].citations = arr
  } catch (e) {
    console.error('解析引用失败:', e)
  }
  continue
}
```

### 1.3.5 前端渲染

`renderMarkdown` 里加一个后处理：

```ts
function renderMarkdown(content: string): string {
  let html = marked(preprocessMarkdown(content)) as string
  // 把 [1] [2] 改成可点击的 sup
  html = html.replace(/\[(\d+)\]/g, (_, idx) =>
    `<sup class="citation-ref" data-id="${idx}">[${idx}]</sup>`
  )
  return html
}
```

点击事件委托在 `message-list` 上（监听 `.citation-ref` 的 click），跳转 `/article/{articleId}` 或弹 popover 显示 citation snippet。

> 论文 / 答辩亮点："带溯源的 RAG（Citation-Grounded Retrieval-Augmented Generation）"，是 Perplexity / Claude / ChatGPT Search 的统一范式。

---

# Phase 2：文档结构感知的检索

> **方案更新（2026-08-21）**：本节下方的“Markdown/HTML 分流 + 每段最长 800 字 + `parent_chunks` 前后两段”属于早期设计，仅保留作为历史背景，不再作为实现依据。后续分片实现统一以 [`23-structured-article-chunking.md`](23-structured-article-chunking.md) 为准：HTML DOM 与 Markdown AST 先归一为统一 Block，结构边界优先，只在语义单元被迫拆开时使用条件式 overlap，首轮评测基线为 `target=480 / hardMax=700 / forcedOverlap=64` tokens，并在 Reranker 之后再做邻块扩展。

## 2.1 Semantic Chunking（Java 侧索引流程改造）

### 2.1.1 规则

当前文章内容不一定是 Markdown：`Article.contentType` 支持富文本/Markdown，现有 `DocumentChunkService` 会用 Jsoup 把 HTML 压成纯文本，标题层级已经丢失。因此语义分块必须按内容类型分流。

Markdown 文章按 `#` / `##` / `###` 语义边界切分：

- 每段保留 `heading_path = [H1, H2, H3]`
- 每段最长 800 字；超过则按段落再切
- 每段记录**在原文中的前后 chunk_id**（`parent_chunks`），供 Phase 2.2 使用

富文本 HTML 文章按 DOM 结构切分：

- 用 Jsoup 解析 HTML，不要先 `.text()` 压平
- `h1/h2/h3` 更新 `heading_path`
- `p/li/pre/code/blockquote` 作为内容块累积
- 代码块和列表尽量保持完整，不在中间硬切
- 超过 800 字再按段落或句子切分

需要同步改：

- `DocumentChunk` 增加 `categoryId/publishTime/headingPath/parentChunks`
- `DocumentChunk.toEsDocument()` 写入 `category_id/publish_time/heading_path/parent_chunks`
- `ArticleVectorListener` 调 `chunk()` 时传入 `categoryId/publishTime/contentType`
- `AgentEsConstants.VECTOR_INDEX_MAPPING` 增加新字段

### 2.1.2 Java 端伪代码（对应 `EsComponent.writeDoc` / 索引建立逻辑）

```java
List<Chunk> semanticChunk(String markdown) {
    List<Chunk> chunks = new ArrayList<>();
    List<String> headingStack = new ArrayList<>();  // [H1, H2, H3]
    StringBuilder buf = new StringBuilder();

    for (String line : markdown.split("\n")) {
        if (line.matches("^#{1,3} .+")) {
            // 结算上一段
            flush(buf, headingStack, chunks);
            // 更新 heading stack
            int level = countLeadingHash(line);
            while (headingStack.size() >= level) headingStack.remove(headingStack.size() - 1);
            headingStack.add(line.replaceAll("^#+\\s*", ""));
            continue;
        }
        buf.append(line).append("\n");
        if (buf.length() >= 800) flush(buf, headingStack, chunks);
    }
    flush(buf, headingStack, chunks);

    // 回填 parent_chunks（前后 2 段）
    for (int i = 0; i < chunks.size(); i++) {
        List<String> parents = new ArrayList<>();
        if (i - 2 >= 0) parents.add(chunks.get(i - 2).chunkId);
        if (i - 1 >= 0) parents.add(chunks.get(i - 1).chunkId);
        if (i + 1 < chunks.size()) parents.add(chunks.get(i + 1).chunkId);
        if (i + 2 < chunks.size()) parents.add(chunks.get(i + 2).chunkId);
        chunks.get(i).parentChunks = parents;
    }
    return chunks;
}
```

### 2.1.3 迁移策略

- 写 Java 的**一次性回灌任务**（`ArticleReindexController`），从 `article_info` 读所有已发布文章 → 新算法重切 → 发 MQ → ES consumer 重建 chunk
- 不影响运行中的检索（原索引 alias 切换）

---

## 2.2 Parent Document Expander

### 2.2.1 思路

- 向量检索命中**小 chunk**（400~800 字）保证向量不模糊
- 命中后，把该 chunk 的 `parent_chunks` 一起拉回来作为上下文
- 给 LLM 的是"命中段 + 前后段"的完整窗口

### 2.2.2 实现

```python
# python-agent/app/services/parent_expander.py
from app.clients.es_client import EsVectorStore


class ParentExpander:
    INDEX = "article_vectors"

    def __init__(self):
        self._es = EsVectorStore()

    async def expand(self, chunks: list[dict]) -> list[dict]:
        """
        为每个 chunk 拉回其 parent_chunks 的内容，拼在 chunk['content'] 后。
        去重：同一个 article_id 下重叠命中的 parent 只拉一次。
        """
        all_ids = set()
        for c in chunks:
            all_ids.update(c.get("parent_chunks", []))

        if not all_ids:
            return chunks

        resp = await self._es.client.search(
            index=self.INDEX,
            body={
                "query": {"terms": {"chunk_id": list(all_ids)}},
                "size": len(all_ids),
            },
        )
        parent_map = {
            h["_source"]["chunk_id"]: h["_source"].get("chunk_content", "")
            for h in resp.get("hits", {}).get("hits", [])
        }

        for c in chunks:
            extras = [parent_map.get(pid, "") for pid in c.get("parent_chunks", [])]
            extras = [x for x in extras if x]
            if extras:
                c["content"] = (c.get("content") or "") + "\n\n" + "\n\n".join(extras)
        return chunks
```

### 2.2.3 接入

search_worker 流水线变为：

```python
candidates = await retrieval_service_instance.hybrid_search(
    semantic_queries=rewrite_result["semantic_queries"],
    keywords=rewrite_result["keywords"] + resolved_filters.soft_terms,
    filters=resolved_filters,
    search_mode=rewrite_result.get("search_mode", "hybrid"),
    top_k=settings.COARSE_TOP_K,
)                                                            # RRF 检索小 chunk
candidates = await parent_expander.expand(candidates)        # 扩大窗口
ranked = await reranker_service.rerank(task_input, candidates)
citations, rag_context = citation_builder_instance.build(ranked)
```

> 论文章节点："Chunk 粒度消融实验：400 / 800 / 1500 字 + Parent Expander 对答案质量的影响"。

---

# Phase 3：高级增强（可选，视时间取舍）

## 3.1 CRAG 风格的检索后校验

修订：不要默认在 rerank 前对所有粗召回 chunk 跑 CRAG。当前已有 DashScope Reranker，CRAG 会增加 N 次 LLM 调用，和 rerank 职责部分重叠。推荐触发式策略：

- 先执行 RRF + Reranker
- 如果 `ranked` 为空、最高分低于阈值、或 `need_web_search=true`，再对 Top-N 候选做 CRAG
- CRAG 判定不足时再触发 web_search，并把 web 结果一起纳入 citation

这样 CRAG 是“低置信度纠偏”，不是每次请求的固定成本。

```python
# python-agent/app/services/crag_grader.py
import asyncio
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from app.config import get_llm


class ChunkRelevance(BaseModel):
    label: str = Field(description="Correct | Ambiguous | Incorrect")
    reason: str = Field(default="")


GRADE_PROMPT = """判断以下检索片段对于用户问题是否相关：
- Correct: 直接回答了问题或包含关键信息
- Ambiguous: 只部分相关或侧面沾边
- Incorrect: 完全无关

用户问题: {query}
检索片段: {snippet}
"""


class CRAGGrader:
    def __init__(self):
        self.llm = get_llm(temperature=0).with_structured_output(
            ChunkRelevance, method="function_calling"
        )

    async def grade_batch(self, query: str, chunks: list[dict]) -> list[dict]:
        async def _grade(c):
            try:
                r = await self.llm.ainvoke([HumanMessage(
                    content=GRADE_PROMPT.format(query=query, snippet=c.get("content", "")[:500])
                )])
                return {**c, "crag_label": r.label}
            except Exception:
                return {**c, "crag_label": "Ambiguous"}   # 降级默认保留

        return await asyncio.gather(*[_grade(c) for c in chunks])

    @staticmethod
    def filter(graded: list[dict]) -> tuple[list[dict], bool]:
        correct   = [c for c in graded if c["crag_label"] == "Correct"]
        ambiguous = [c for c in graded if c["crag_label"] == "Ambiguous"]

        if correct:
            return correct, False                 # 足够好，不需要 web 兜底
        if ambiguous:
            return ambiguous, True                # 勉强用，建议 web 兜底
        return [], True                           # 全挂了，强制 web 兜底
```

search_worker 的兜底策略：

```python
def to_web_chunks(web_results: list[dict]) -> list[dict]:
    return [{
        "article_id": f"web_{i}",
        "title": item.get("title", ""),
        "content": item.get("content") or item.get("snippet", ""),
        "chunk_index": i,
        "source": "web",
        "url": item.get("url", ""),
    } for i, item in enumerate(web_results)]


ranked = await reranker_service.rerank(task_input, candidates)
low_confidence = not ranked or ranked[0].get("score", 0.0) < settings.RERANK_CONFIDENCE_THRESHOLD

if settings.RAG_USE_CRAG_GRADER and (low_confidence or need_web_search):
    graded = await crag_grader.grade_batch(task_input, ranked or candidates[: settings.CRAG_TOP_N])
    filtered, need_web = CRAGGrader.filter(graded)
else:
    filtered, need_web = ranked, False

if need_web or need_web_search:
    web_results = await do_search(task_input, size=5)
    filtered.extend(to_web_chunks(web_results))
```

## 3.2 检索结果缓存

```python
# python-agent/app/services/retrieval_service.py
import hashlib
import json
from app.clients.es_client import EsVectorStore, EsComponent
from app.clients.redis_client import RedisClient

class RetrievalService:
    CACHE_TTL = 600  # 10 分钟

    def __init__(self):
        self._vector_store = EsVectorStore()
        self._article_search = EsComponent()
        self._redis = RedisClient()

    async def hybrid_search(self, semantic_queries, keywords, resolved_filters, search_mode="hybrid", top_k=20):
        cache_key = self._cache_key(semantic_queries, keywords, resolved_filters, search_mode, top_k)
        cached = await self._redis.get(cache_key)
        if cached:
            return json.loads(cached)

        result = await self._hybrid_search_inner(
            semantic_queries=semantic_queries,
            keywords=keywords,
            resolved_filters=resolved_filters,
            search_mode=search_mode,
            top_k=top_k,
        )
        await self._redis.set(cache_key, json.dumps(result, default=str), ex=self.CACHE_TTL)
        return result

    @staticmethod
    def _cache_key(semantic_queries, keywords, resolved_filters, search_mode, top_k):
        payload = {
            "sq": sorted(semantic_queries),
            "kw": sorted(keywords),
            "f":  resolved_filters.model_dump(),
            "mode": search_mode,
            "k":  top_k,
        }
        h = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return f"py_rag:{h}"
```

这里的 `_hybrid_search_inner` 就是 1.2.3 里不带缓存的 RRF 主逻辑，缓存只包在外层，不改变召回和排序结果。

## 3.3 评测 Harness

### 3.3.1 数据集

在 `python-agent/eval/` 下建 `dataset.jsonl`：

```json
{"query":"Spring Boot 怎么配置数据源","expected_article_ids":["xxx","yyy"],"expected_keywords":["DataSource","application.yml"]}
{"query":"最近一周有什么 Vue3 文章","expected_tags":["Vue"],"expected_time_range":"week"}
{"query":"小王写的 Redis 文章","expected_author":"小王","expected_keywords":["Redis","缓存"]}
```

后续样本保持同样结构追加即可，先手工标 50 ~ 100 条就够跑趋势。

### 3.3.2 评测指标

| 指标 | 公式 | 含义 |
| --- | --- | --- |
| **Recall@K** | 命中 article_ids 中有几个出现在 top-K | 召回覆盖率 |
| **MRR** | $\frac{1}{\|D\|}\sum \frac{1}{rank_{first\_hit}}$ | 第一命中的排名倒数 |
| **nDCG@K** | 标准 nDCG | 排序质量 |
| **Citation Precision** | 回答里每个 [i] 是否真的支撑了那句话（LLM-as-judge） | Citation 质量 |
| **Faithfulness**（RAGAS） | 回答中每个陈述能否被 context 支持 | 无幻觉 |
| **Context Recall**（RAGAS） | expected 答案 keywords 是否在 context 中 | 信息是否到位 |

### 3.3.3 脚手架

```python
# python-agent/eval/run_eval.py
import asyncio, json
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall
from app.services.retrieval_service import RetrievalService
from app.services.query_rewrite import QueryRewriteService
from app.services.filter_resolver import FilterResolver

async def run():
    rs = RetrievalService()
    qr = QueryRewriteService()
    fr = FilterResolver()
    rows = []
    with open("eval/dataset.jsonl", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            rw = await qr.rewrite(item["query"], [])
            resolved_filters = await fr.resolve(rw["filters"])
            chunks = await rs.hybrid_search(
                rw["semantic_queries"],
                rw["keywords"],
                resolved_filters,
                search_mode=rw.get("search_mode", "hybrid"),
                top_k=10,
            )
            rows.append({
                "question": item["query"],
                "contexts": [c["content"] for c in chunks],
                "ground_truths": [" ".join(item.get("expected_keywords", []))],
                # answer 要跑一遍完整 pipeline 拿到
                "answer": await run_full_pipeline(item["query"]),
            })

    ds = Dataset.from_list(rows)
    report = evaluate(ds, metrics=[faithfulness, answer_relevancy, context_recall])
    print(report)
    report.to_csv("eval/report.csv")

if __name__ == "__main__":
    asyncio.run(run())
```

### 3.3.4 A/B 对照

把每个优化点写成 feature flag，跑两次 eval 对比：

```
# .env
RAG_USE_RRF=true
RAG_USE_PARENT_EXPAND=true
RAG_USE_CRAG_GRADER=false
RAG_USE_CITATION=true
```

论文表格直接出：

| 配置 | Recall@5 | MRR | Faithfulness |
| --- | --- | --- | --- |
| Baseline（线性加权） | 0.62 | 0.51 | 0.73 |
| +RRF | 0.71 | 0.59 | 0.75 |
| +RRF +Parent | 0.74 | 0.64 | 0.81 |
| +RRF +Parent +Citation+CRAG | 0.78 | 0.69 | 0.89 |

---

## 3. 最小任务拆分（可直接当 tasks.md 用）

- [ ] 1. `query_rewrite.py` 加 `QueryFilters` / `search_mode` / `need_web_search` schema + prompt 更新；LLM 只输出 `category_names/author_name`，不输出数据库 ID
- [ ] 2. 新建 `filter_resolver.py`，把 `category_names/author_name` 查 MySQL 解析为 `category_ids/author_ids`；查不到或不唯一时放入 `soft_terms`，不做硬过滤
- [ ] 3. `EsVectorStore.search()` / `EsComponent.search()` 支持可选 ES filter
- [ ] 4. 新建 `retrieval_service.py`，首期手写 RRF 融合 `article_vectors` + `article` 双索引
- [ ] 5. `search_worker.py` 去除 `execute_coarse_retrieval`，改调 `filter_resolver + retrieval_service`，按 `search_mode/need_web_search` 控制平台检索和联网兜底
- [ ] 6. Java 侧补齐 `article_vectors` 元数据：新增 `category_id/publish_time`，同时确认现有 `user_id/tags` 在历史重建中保留
- [ ] 7. 新建 `citation_builder.py`，生成 citations + rag_context；web_search 结果也要能生成 citation
- [ ] 8. `SEARCH_SYSTEM_PROMPT` 更新为强制引用；rag_context 用 `[i] title\ncontent` 格式
- [ ] 9. `search_worker.py` 返回 `citations` 到 state；`main.py` 在流结束处下发 `__CITATIONS__`
- [ ] 10. 前端 `AiChat.vue` 解析 `__CITATIONS__` + 渲染 `[n]` 为可点击 sup + 点击跳转
- [ ] 11.* Java 侧语义分块：Markdown 按 `#/##/###`，HTML 按 DOM 标题/段落/代码块切，生成 `heading_path/parent_chunks`
- [ ] 12.* `parent_expander.py` + 接入
- [ ] 13.** `crag_grader.py` + feature flag 接入，仅低置信度时触发
- [ ] 14.** `retrieval_service` 加 Redis 缓存
- [ ] 15.** Eval harness（dataset + RAGAS + A/B 报告）

## 4. 关键决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| Rerank API / 本地模型 | **用 API**（现状） | DashScope qwen3-vl-rerank 已足够好；免 GPU；成本低 |
| 融合策略 | **手写 RRF 优先，ES 原生 RRF 后置** | 兼容当前双索引；后续可迁到单索引原生 RRF |
| Chunking | **HTML/Markdown 结构分块 + parent** | 适配当前富文本和 Markdown 混合内容 |
| Citation | **[n] 标注 + 前端悬浮卡片** | Perplexity 风格，答辩亮点 |
| CRAG | Phase 3 低置信度触发 | 避免每次请求固定增加 N 次 LLM 调用 |
| 评测 | RAGAS + 自建 50 条 | 论文必备 |

## 5. 性能与成本预估

| 阶段 | 额外 API 调用 | 额外延迟（估） |
| --- | --- | --- |
| Query Rewrite v2 | 0（字段扩展） | 0 |
| RRF 融合 | 0（多次 ES 查询，当前本来就多路召回） | 小幅增加排序开销 |
| Parent Expand | 1 次 ES `terms` 查询 | +30ms |
| Citation Build | 0 | 0 |
| CRAG Grader | 低置信度时 Top-N 次 LLM | 仅异常/低置信度路径增加 |
| Retrieval Cache | 命中时 -300ms，未命中 0 | 净节省 |

整体 latency 上升可控（<500ms），质量收益明显。

## 6. 风险与回滚

- **ES 字段兼容**：`category_id/publish_time/heading_path/parent_chunks` 未重建前不能作为强依赖；filter 必须按字段存在情况开关化。分类/作者解析不确定时必须降级为 `soft_terms`，不能硬过滤
- **ES 原生 RRF 兼容**：`retriever: { rrf: [...] }` 放到后续版本；首期手写 RRF 避免 ES 版本和双索引限制
- **阿里云 rerank 限流**：失败时沿用当前 fallback（取 top_k）不变
- **LLM 引用违规**：prompt 里显式要求；web_search 结果也进入 citation；eval 跑 LLM-as-judge 对引用做抽样检查；坏 case 多就上 citation 后处理规则校验

---

## 附录 A：ES 原生 RRF（后续可选）

当前首期方案已经在 `retrieval_service.py` 中手写 RRF，兼容 `article_vectors + article` 双索引。下面示例只适用于后续版本：关键词 BM25 路也迁入 `article_vectors`，并且 ES 版本支持 `retriever.rrf`。

```python
async def native_rrf_search(self, semantic_queries, keywords, filters, top_k):
    filter_clauses = self._build_filter_clauses(filters)

    # 注意：这是“拼接后的 query embedding”，不是多个 query 向量平均。
    # 如果要严格多 query RRF，仍应每个 semantic_query 分别 KNN 后手写融合。
    q_vec = await self._embedding.aembed(" ".join(semantic_queries))

    body = {
        "retriever": {
            "rrf": {
                "rank_constant": 60,
                "rank_window_size": top_k * 4,
                "retrievers": [
                    {
                        "knn": {
                            "field": "content_vector",
                            "query_vector": q_vec,
                            "k": top_k * 2,
                            "num_candidates": top_k * 4,
                            "filter": filter_clauses or None,
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "must": [{
                                        "multi_match": {
                                            "query": " ".join(keywords),
                                            "fields": ["title^2", "chunk_content", "tags"],
                                            "operator": "or",
                                        }
                                    }],
                                    "filter": filter_clauses or [],
                                }
                            }
                        }
                    },
                ],
            }
        },
        "size": top_k,
    }

    resp = await self._es_store.client.search(index="article_vectors", body=body)
    return self._parse_hits(resp)
```

回滚策略：

- ES 原生 RRF 失败时直接切回首期手写 RRF。
- 不要把 ES 原生 RRF 作为唯一实现；它依赖 ES 版本、索引字段和单索引检索结构。

## 附录 B：手写 RRF 核心公式

```python
def rrf_merge(ranked_lists: list[list[dict]], top_k: int, k_rrf: int = 60) -> list[dict]:
    merged: dict[str, dict] = {}

    for docs in ranked_lists:
        for rank, doc in enumerate(docs, start=1):
            key = doc.get("doc_key") or str(doc.get("article_id"))
            item = merged.setdefault(key, {"doc": doc, "score": 0.0})
            item["score"] += 1.0 / (k_rrf + rank)

    out = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    result = []
    for item in out[:top_k]:
        doc = dict(item["doc"])
        doc["rrf_score"] = item["score"]
        result.append(doc)
    return result
```

---

## 附录 C：推荐阅读

- ES RRF 官方文档：https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html
- CRAG 论文：[Corrective Retrieval Augmented Generation, 2024](https://arxiv.org/abs/2401.15884)
- Self-RAG：[Learning to Retrieve, Generate and Critique, 2023](https://arxiv.org/abs/2310.11511)
- RAGAS：https://docs.ragas.io/
- Parent Document Retriever（LangChain docs）：https://python.langchain.com/docs/how_to/parent_document_retriever/
- Perplexity Citation UX：https://docs.perplexity.ai/
