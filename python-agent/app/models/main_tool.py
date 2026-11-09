"""Typed tool requests. Identity, capability grants and execution are server-owned."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from app.services.query_rewrite import QueryFilters

# MySQL BIGINT and the Java/protobuf RPC contract use signed 64-bit IDs.
# Reject overflow while Main can still repair its decision, before any RPC.
BlogId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)


class KnowledgeArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=4000)
    allow_web: bool = False
    article_ids: list[BlogId] = Field(default_factory=list, max_length=8)
    filters: QueryFilters | None = None
    search_query: str | None = Field(default=None, min_length=1, max_length=200)


class MemoryArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=4000)


class DraftArgs(ToolArgs):
    article_id: BlogId | None = None
    keyword: str | None = Field(default=None, min_length=1, max_length=200)


class EditorArgs(ToolArgs):
    part: Literal['document', 'selection'] = 'document'


class WebSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=128)


class WebpageArgs(ToolArgs):
    urls: list[str] = Field(min_length=1, max_length=3)


class CommentsArgs(ToolArgs):
    article_id: BlogId
    limit: int = Field(default=20, ge=1, le=50)


class UserArticlesArgs(ToolArgs):
    user_id: BlogId
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=10, ge=1, le=50)


class TrendingArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=50)


class ResultSelection(ToolArgs):
    source_task_id: str = Field(min_length=1, max_length=80)
    start_char: int = Field(default=0, ge=0, le=1048576)
    max_chars: int = Field(default=12000, ge=500, le=24000)
    query: str | None = Field(default=None, min_length=1, max_length=200)
    citation_id: str | None = Field(default=None, min_length=1, max_length=160)
    queries: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, min_length=1, max_length=5)
    section_id: str | None = Field(default=None, min_length=1, max_length=80)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode='after')
    def locator(self):
        if sum(value is not None for value in (self.query, self.queries, self.citation_id, self.section_id)) > 1:
            raise ValueError('关键词、多个关键词、章节和引用定位只能选择一种')
        if self.queries is not None:
            self.queries = list(dict.fromkeys(word.strip() for word in self.queries))
            if not all(self.queries):
                raise ValueError('关键词不能为空白')
        if (self.query is not None or self.queries is not None or self.citation_id is not None or self.section_id is not None or self.cursor) and self.start_char:
            raise ValueError('定位读取不能混入字符起点')
        return self


class ResultArgs(ResultSelection):
    allow_web: bool = False


class ResultsArgs(ToolArgs):
    requests: list[ResultSelection] = Field(min_length=1, max_length=4)
    allow_web: bool = False


class HistorySearchArgs(ToolArgs):
    keyword: str = Field(min_length=1, max_length=100)
    before_message_id: BlogId | None = None
    limit: int = Field(default=8, ge=1, le=12)


class HistoryReadArgs(ToolArgs):
    message_ids: list[BlogId] = Field(min_length=1, max_length=6)
    start_char: int = Field(default=0, ge=0, le=1048576)
    max_chars: int = Field(default=4000, ge=200, le=4000)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(default='', pattern=r'^(?:[a-z][a-z0-9_]{0,39})?$')
    required_skills: list[str] = Field(default_factory=list, max_length=4)


class SearchKnowledge(ToolRequest):
    name: Literal['search_knowledge']
    args: KnowledgeArgs


class ReadMemory(ToolRequest):
    name: Literal['read_memory']
    args: MemoryArgs


class ReadDraft(ToolRequest):
    name: Literal['read_draft']
    args: DraftArgs


class ReadEditor(ToolRequest):
    name: Literal['read_editor']
    args: EditorArgs


class WebSearch(ToolRequest):
    name: Literal['web_search']
    args: WebSearchArgs


class ReadWebpage(ToolRequest):
    name: Literal['read_webpage']
    args: WebpageArgs


class GetComments(ToolRequest):
    name: Literal['get_article_comments']
    args: CommentsArgs


class GetUserArticles(ToolRequest):
    name: Literal['get_user_articles']
    args: UserArticlesArgs


class GetTrendingTopics(ToolRequest):
    name: Literal['get_trending_topics']
    args: TrendingArgs


class ReadTaskResult(ToolRequest):
    name: Literal['read_task_result']
    args: ResultArgs


class ReadTaskResults(ToolRequest):
    name: Literal['read_task_results']
    args: ResultsArgs


class SearchHistory(ToolRequest):
    name: Literal['search_conversation_history']
    args: HistorySearchArgs


class ReadHistory(ToolRequest):
    name: Literal['read_conversation_messages']
    args: HistoryReadArgs


MainToolCall = Annotated[SearchKnowledge | ReadMemory | ReadDraft | ReadEditor | WebSearch |
    ReadWebpage | GetComments | GetUserArticles | GetTrendingTopics | ReadTaskResult | ReadTaskResults | SearchHistory | ReadHistory,
    Field(discriminator='name')]
tool_call_adapter = TypeAdapter(MainToolCall)


def task_fields(call):
    """Compile validated arguments once; the persisted task carries the exact call."""
    args = call.args
    common = dict(tool_name=call.name, tool_args=args.model_dump(), required_skills=call.required_skills)
    if call.name == 'search_knowledge':
        return common | dict(kind='search', retrieval_target='knowledge', requires_evidence=True,
            instruction=args.query, **args.model_dump(exclude={'query'}))
    if call.name == 'read_memory':
        return common | dict(kind='search', retrieval_target='memory', instruction=args.query)
    if call.name == 'read_draft':
        return common | dict(kind='search', retrieval_target='drafts', instruction='读取本人草稿' if args.article_id else '查找本人草稿',
            article_ids=[args.article_id] if args.article_id else [], search_query=args.keyword)
    if call.name == 'read_editor':
        return common | dict(kind='search', retrieval_target='editor', instruction='读取本轮编辑器快照', editor_part=args.part)
    if call.name == 'read_webpage':
        return common | dict(kind='search', retrieval_target='knowledge', requires_evidence=True,
            instruction='读取指定公开网页', allow_web=True, urls=args.urls)
    if call.name == 'web_search':
        return common | dict(kind='search', retrieval_target='knowledge', requires_evidence=True,
            instruction=args.query, search_query=args.query, filters=QueryFilters(), allow_web=True)
    label = {'get_article_comments': '读取文章评论', 'get_user_articles': '读取用户公开文章',
             'get_trending_topics': '读取热门话题', 'read_task_result': '回读已完成的公共任务结果',
             'read_task_results': '批量回读已完成的公共任务结果',
             'search_conversation_history': '搜索当前会话历史', 'read_conversation_messages': '读取当前会话原文'}[call.name]
    return common | dict(kind='tool', instruction=label)


def call_from_retrieval(request):
    """Only internal recovery/checkpoint migration uses the old retrieval contract."""
    common = dict(task_id=request.task_id, required_skills=request.required_skills)
    if request.target == 'knowledge':
        if request.urls:
            return ReadWebpage(name='read_webpage', args={'urls': request.urls}, **common)
        return SearchKnowledge(name='search_knowledge', args=KnowledgeArgs(query=request.instruction,
            allow_web=request.allow_web, article_ids=request.article_ids, filters=request.filters,
            search_query=request.search_query), **common)
    if request.target == 'memory':
        return ReadMemory(name='read_memory', args={'query': request.instruction}, **common)
    if request.target == 'drafts':
        return ReadDraft(name='read_draft', args={'article_id': next(iter(request.article_ids), None),
            'keyword': request.search_query}, **common)
    return ReadEditor(name='read_editor', args={'part': request.editor_part}, **common)
