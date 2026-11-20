from langchain_core.tools import tool

from app.rpc.blog_client import public_read


@tool
async def get_trending_topics(limit: int=10)->str:
    """
    获取平台当前热门标签和话题。

    Args:
        limit: 返回数量
    Returns:
        热门标签列表，包含标签名和文章数量
    """
    rows = await public_read('trending', limit=limit)
    if not rows:
        return "暂无热门标签"
    topics = []
    for r in rows:
        row = r
        topics.append(f"- {row['tag_name']}（{row['use_count']} 篇文章）")
    return "当前平台热门话题：\n" + "\n".join(topics)
