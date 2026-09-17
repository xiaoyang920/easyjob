from langchain_core.tools import tool

from app.clients.mysql_client import db


@tool
async def get_trending_topics(limit: int=10)->str:
    """
    获取平台当前热门标签和话题。

    Args:
        limit: 返回数量
    Returns:
        热门标签列表，包含标签名和文章数量
    """
    rows = await db.fetch_all(
        """
        SELECT tag_name, use_count
        FROM article_tag
        ORDER BY use_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    if not rows:
        return "暂无热门标签"
    topics = []
    for r in rows:
        row = dict(r._mapping)
        topics.append(f"- {row['tag_name']}（{row['use_count']} 篇文章）")
    return "当前平台热门话题：\n" + "\n".join(topics)