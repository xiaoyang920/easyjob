import re
from datetime import datetime

from app.clients.mysql_client import db
from app.models.draft import DraftOutput, DRAFT_SUMMARY_MAX_LENGTH, DRAFT_SUMMARY_TARGET_LENGTH


async def save_draft_to_article_info(user_id: int, draft: DraftOutput, article_id: int)->int:
    """Phase 0 compatibility writer; checkpointed article_id makes replay idempotent."""
    now = datetime.now()
    title = (draft.title or "").strip() \
            or extract_title_from_draft(draft.content) \
            or f"AI 草稿·{now.strftime('%Y-%m-%d %H:%M')}"
    title = title[:50]

    summary = (draft.summary or "").strip() or _make_fallback_summary(draft.content)
    summary = summary[:DRAFT_SUMMARY_MAX_LENGTH]

    await db.execute(
        """
        INSERT INTO article_info (
            article_id, user_id,
            title, cover_image, summary, content, content_type,
            category_id, tags,
            view_count, like_count, collect_count, comment_count, share_count,
            status, is_top, is_essence, is_original,
            publish_time, create_time, update_time, deleted
        ) VALUES (
            :aid, :uid,
            :title, NULL, :summary, :content, 2,
            NULL, '',
            0, 0, 0, 0, 0,
            0, 0, 0, 1,
            NULL, :now, :now, 0
        ) ON DUPLICATE KEY UPDATE article_id = article_id
        """,
        {
            "aid": article_id,
            "uid": user_id,
            "title": title,
            "summary": summary,
            "content": draft.content,
            "now": now,
        },
    )
    row = await db.fetch_one(
        "SELECT user_id FROM article_info WHERE article_id = :aid",
        {"aid": article_id},
    )
    if not row or int(row._mapping["user_id"]) != user_id:
        raise ValueError("草稿保存结果不属于当前用户")
    return article_id


def extract_title_from_draft(content: str) -> str:
    """从 markdown 首个 `# 标题` 抽取标题；抽不到返回空字符串"""
    if not content:
        return ""
    import re
    m = re.search(r"^\s*#\s+(.+)$", content, flags=re.MULTILINE)
    if not m:
        return ""
    return m.group(1).strip()[:50]


def _make_fallback_summary(content: str) -> str:
    """从正文抽不超过目标长度的摘要（去 markdown 语法 + 去多余空白）。"""
    if not content:
        return ""
    plain = re.sub(r"^#+\s+.+$", "", content, flags=re.MULTILINE)  # 去标题行
    plain = re.sub(r"```[\s\S]*?```", "", plain)  # 去代码块
    plain = re.sub(r"[*_`#>\[\]()]+", "", plain)  # 去行内 markdown 标记
    plain = re.sub(r"\s+", " ", plain).strip()
    clipped = plain[:DRAFT_SUMMARY_TARGET_LENGTH]
    if len(plain) > DRAFT_SUMMARY_TARGET_LENGTH:
        boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", ". ", "! ", "? "))
        if boundary >= DRAFT_SUMMARY_TARGET_LENGTH // 2:
            clipped = clipped[:boundary + 1]
    return clipped
