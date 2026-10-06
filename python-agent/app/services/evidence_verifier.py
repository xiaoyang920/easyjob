"""Recheck visibility and source freshness before approval or final delivery."""
import hashlib
from app.clients.mysql_client import db


async def verify_public_evidence(citations):
    versions = {}
    for c in citations:
        if c.get("articleId") and c.get("sourceHash"):
            versions.setdefault(str(c["articleId"]), set()).add(c["sourceHash"])
    if any(len(values) > 1 for values in versions.values()):
        raise ValueError("同一文章存在不同版本的证据")
    expected = {str(c["articleId"]): c["sourceHash"] for c in citations
                if c.get("articleId") and c.get("sourceHash")}
    if not expected:
        return
    placeholders = ",".join(f":id{i}" for i in range(len(expected)))
    rows = await db.fetch_all(f"""SELECT article_id,content FROM article_info WHERE article_id IN ({placeholders})
        AND status=1 AND deleted=0 AND required_level=0""", {f"id{i}": aid for i, aid in enumerate(expected)})
    actual = {str(r._mapping["article_id"]): hashlib.sha256((r._mapping["content"] or "").encode()).hexdigest() for r in rows}
    if actual != expected:
        raise ValueError("证据已更新、下架或删除，需要重新检索")
