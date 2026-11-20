from langchain_core.tools import tool

from app.rpc.blog_client import public_read


@tool
async def get_article_comments(article_id: int,limit: int=20)->str:
    """
    获取指定文章的评论列表。

    Args:
        article_id: 文章 ID
        limit: 返回数量
    Returns:
        评论列表，包含评论内容、评论者、时间
    """
    rows = await public_read('comments', target_id=article_id, limit=limit)
    if not rows:
        return "该文章暂无评论"
    comment = []
    for r in rows:
        row = r
        comment.append(
            f"- {row['nick_name']}：{row['content']}（{row['create_time']}）"
        )
    return "\n".join(comment)
