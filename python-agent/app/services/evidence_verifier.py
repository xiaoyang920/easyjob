"""Recheck visibility and source freshness before approval or final delivery."""
import hashlib
from app.rpc.blog_client import public_read


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
    rows = await public_read('published', ids=list(expected))
    actual = {str(r["article_id"]): hashlib.sha256((r["content"] or "").encode()).hexdigest() for r in rows}
    if actual != expected:
        raise ValueError("证据已更新、下架或删除，需要重新检索")
