from langchain_core.tools import tool

from app.rpc.blog_client import public_read


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
    rows = await public_read('user_articles', target_id=int(user_id), page=page, limit=page_size)
    if not rows:
        return "该用户暂无已发布文章"
    articles = []
    for r in rows:
        row = r
        articles.append(
            f"- [{row['title']}] 浏览:{row['view_count']} 点赞:{row['like_count']} "
            f"收藏:{row['collect_count']} 发布于:{row['create_time']}"
        )
    return "\n".join(articles)
