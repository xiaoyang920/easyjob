from langchain_core.tools import tool

from app.clients.mysql_client import db


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
    rows = await db.fetch_all(
        """
        SELECT c.content, u.nick_name, c.create_time
        FROM article_comment c
        JOIN user_info u ON c.user_id = u.user_id
        WHERE c.article_id = :aid
        ORDER BY c.create_time DESC
        LIMIT :limit
        """,
        {"aid": article_id, "limit": limit},
    )
    if not rows:
        return "该文章暂无评论"
    comment = []
    for r in rows:
        row = dict(r._mapping)
        comment.append(
            f"- {row['nick_name']}：{row['content']}（{row['create_time']}）"
        )
    return "\n".join(comment)
