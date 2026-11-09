"""Main's read-only tool catalog. Adapters reuse business services, never call an LLM to select tools."""
from dataclasses import dataclass
from typing import Callable

from app.graph.nodes.search_worker import retrieve_evidence
from app.graph.nodes.memory_retrieval import retrieve_memory
from app.services.private_drafts import retrieve_drafts
from app.services.editor_tools import read_editor
from app.services.context_tools import read_task_result, read_task_results, conversation_history


@dataclass(frozen=True)
class MainToolSpec:
    capability: str
    label: str
    handler: Callable
    raw_evidence: bool = False


async def _public_tool(context):
    from app.services.tool_registry import tool_registry
    from app.services.tool_recovery import success_text
    task = context['current_task']
    tool = tool_registry.get_local_tool(task['tool_name'])
    policy = tool_registry.policy_for(tool)
    if policy is None or not policy.read_only or policy.capability != 'platform_read':
        raise PermissionError('当前工具不在受控只读注册表中')
    args = dict(task['tool_args'])
    if task['tool_name'] == 'get_user_articles':
        args['user_id'] = str(args['user_id'])
    result = await tool.ainvoke(args)
    return {'status': 'succeeded', 'result': success_text(result), 'citations': [], 'article_cards': []}


async def _knowledge(context):
    return await retrieve_evidence(context)


async def _memory(context):
    return await retrieve_memory(context)


async def _draft(context):
    return await retrieve_drafts(context)


async def _editor(context):
    return await read_editor(context)


MAIN_TOOLS = {
    'read_task_result': MainToolSpec('platform_read', '回读任务结果', read_task_result),
    'read_task_results': MainToolSpec('platform_read', '批量回读任务结果', read_task_results),
    'search_conversation_history': MainToolSpec('conversation_read', '搜索历史对话', conversation_history),
    'read_conversation_messages': MainToolSpec('conversation_read', '读取历史原话', conversation_history),
    'search_knowledge': MainToolSpec('platform_read', '检索资料', _knowledge, True),
    'read_memory': MainToolSpec('memory_read', '召回相关记忆', _memory),
    'read_draft': MainToolSpec('own_draft_read', '读取本人草稿', _draft),
    # This reads the snapshot uploaded with the request, not a live browser RPC.
    'read_editor': MainToolSpec('editor_read', '读取编辑器快照', _editor),
    'web_search': MainToolSpec('web_search', '搜索公开网页', _knowledge, True),
    'read_webpage': MainToolSpec('web_search', '读取公开网页', _knowledge, True),
    'get_article_comments': MainToolSpec('platform_read', '读取文章评论', _public_tool),
    'get_user_articles': MainToolSpec('platform_read', '读取用户公开文章', _public_tool),
    'get_trending_topics': MainToolSpec('platform_read', '读取热门话题', _public_tool),
}
