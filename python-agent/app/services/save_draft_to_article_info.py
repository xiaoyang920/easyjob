import re
from datetime import datetime

from app.clients.mysql_client import db
from app.models.draft import DraftOutput, DRAFT_SUMMARY_MAX_LENGTH, DRAFT_SUMMARY_TARGET_LENGTH


async def save_draft_to_article_info(user_id: int, draft: DraftOutput, article_id: int) -> int:
    """Retired writer: all saves require the approved Java draft gateway."""
    raise RuntimeError("Direct article_info draft writes are disabled; use draft_gateway.save_approved_draft")


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
