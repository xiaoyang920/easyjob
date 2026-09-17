from langchain_core.tools import tool

from app.clients.mysql_client import db


@tool
async def get_user_articles(user_id:str, page:int=1, page_size:int=10)->str:
    """
    获取指定用户的文章列表。

    Args:
        user_id: 用户 ID
        page: 页码
        page_size: 每页数量
    Returns:
        文章列表，包含标题、摘要、发布时间、浏览量等
    """
    rows = await db.fetch_all(
        """
        SELECT article_id,title,summary,create_time,view_count,like_count,collect_count
        FROM article_info
        WHERE user_id = :uid AND status = 1
        ORDER BY create_time DESC 
        LIMIT :limit OFFSET :offset
        """,
        {"uid": user_id, "limit": page_size, "offset": (page - 1) * page_size},
    )
    if not rows:
        return "该用户暂无已发布文章"
    articles = []
    for r in rows:
        row = dict(r._mapping)
        articles.append(
            f"- [{row['title']}] 浏览:{row['view_count']} 点赞:{row['like_count']} "
            f"收藏:{row['collect_count']} 发布于:{row['create_time']}"
        )
    return "\n".join(articles)
