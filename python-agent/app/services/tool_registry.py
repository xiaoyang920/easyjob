import logging

from langchain_core.tools import BaseTool

from app.clients.mcp_client import mcp_manager
from app.tools.article_tool import search_articles_by_knn, search_articles
from app.tools.get_article_comments import get_article_comments
from app.tools.get_trending_topics import get_trending_topics
from app.tools.get_user_articles import get_user_articles
from app.tools.web_search import web_search

log = logging.getLogger(__name__)

class ToolRegistry:
    """
       工具注册中心

       用法:
           registry = ToolRegistry()
           await registry.refresh()  # 刷新 MCP 工具
           tools = registry.get_tools(["search_articles", "web_search", "mcp_xxx"])
       """
    def __init__(self):
        self._local_tools: dict[str, BaseTool] = {
            "search_articles": search_articles,
            "search_articles_by_knn": search_articles_by_knn,
            "web_search": web_search,
            "get_user_articles": get_user_articles,
            "get_trending_topics": get_trending_topics,
            "get_article_comments": get_article_comments,
        }
        self._mcp_tools: dict[str, BaseTool] = {}
    def refresh(self):
        """从 MCP Manager 刷新工具列表"""
        mcp_tools = mcp_manager.get_tools()
        self._mcp_tools = {t.name: t for t in mcp_tools}
        log.info(
            "工具注册中心：本地%d+MCP%d = 总计%d",
            len(self._local_tools),
            len(self._mcp_tools),
            len(self._local_tools) + len(self._mcp_tools),
        )
    def get_all_tools(self)-> list[BaseTool]:
        """获取全部工具"""
        return list(self._local_tools.values()) + list(self._mcp_tools.values())
    def get_tools(self,name: list[str])-> list[BaseTool]:
        """按名称获取指定工具"""
        merged = {**self._local_tools, **self._mcp_tools}
        return [merged[n] for n in name if n in merged]
    def get_tool_descriptions(self)->str:
        """生成工具描述文本，注入给 Planner 做决策"""
        lines = []
        for name, tool in {**self._local_tools, **self._mcp_tools}.items():
            desc = tool.description.split("\n")[0] if tool.description else "无描述"
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

tool_registry = ToolRegistry()