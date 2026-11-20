"""
文章搜索工具
对应 Java: ArticleTool.java
"""
from langchain_core.tools import tool

from app.clients.es_client import EsComponent, EsVectorStore

_es = EsComponent()
_es_vector = EsVectorStore()

@tool
async def search_articles(query: str) -> str:
    """
    搜索平台内的技术文章、职场经验、面试题等内容。
    适合：查找平台已有的知识、经验类内容；writing worker 需要知识点、案例、数据支撑时使用。
    不适合：需要实时数据或平台外信息的问题。

    Args:
        query: 搜索关键词，尽量简洁精确，不超过 20 字
    """
    results = await _es.search(query, page_size=5)
    if not results:
        return "平台内未找到相关文章"
    return "\n".join([f"- [{r['title']}] {r.get('summary', '')[:200]}" for r in results])
@tool
async def search_articles_by_knn(query: str) -> str:
    """
    基于向量 KNN 搜索文章。
    适合：查找平台已有的知识、经验类内容；writing worker 需要知识点、案例、数据支撑时使用。
    不适合：需要实时数据或平台外信息的问题。

    Args:
        query: 搜索关键词，尽量简洁精确，不超过 20 字
    """
    results = await _es_vector.search(query, top_k=5, threshold=0.7)
    if not results:
        return "平台内未找到相关文章"
    return "\n".join([f"- [{r['title']}] {r.get('content', '')[:200]}" for r in results])