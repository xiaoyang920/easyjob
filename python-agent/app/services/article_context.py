"""Current published article is source data, not a restriction on agent tools."""
import hashlib
import re
from html.parser import HTMLParser

from fastapi import HTTPException
from markdown_it import MarkdownIt

from app.config import settings
from app.utils.token_utils import count_tokens, truncate_to_token_budget


class _VisibleArticleText(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "blockquote", "li", "ul", "ol", "table",
              "tr", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
    HIDDEN = {"script", "style", "template", "noscript", "head", "iframe", "object"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r"\s+", "", attrs.get("style") or "").lower()
        hidden = (bool(self.stack and self.stack[-1][1]) or tag in self.HIDDEN
                  or "hidden" in attrs or (attrs.get("aria-hidden") or "").lower() == "true"
                  or "display:none" in style or "visibility:hidden" in style)
        if not hidden:
            if tag in self.BLOCKS or tag == "br":
                self.parts.append("\n")
            elif tag in {"td", "th"}:
                self.parts.append("\t")
            elif tag == "img" and attrs.get("alt"):
                self.parts.append(attrs["alt"])
        if tag not in self.VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        hidden = bool(self.stack and self.stack[-1][1])
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if not hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if any(tag == "pre" for tag, _ in self.stack):
            # Keep indentation/newlines in code. Outside pre, HTML whitespace
            # collapses in the browser and should not create fake paragraph gaps.
            self.parts.append(data)
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def article_text(content: str, content_type: int = 1) -> str:
    rendered = MarkdownIt("commonmark", {"html": False}).render(content) if content_type == 2 else content
    parser = _VisibleArticleText()
    parser.feed(rendered)
    parser.close()
    return parser.text()


class ArticleContextService:
    def __init__(self, reader=None):
        from app.rpc.blog_client import public_read
        self.reader = reader or public_read

    async def load(self, origin_article_id: int, *, max_tokens: int | None = None) -> dict:
        if isinstance(origin_article_id, bool) or origin_article_id <= 0:
            raise HTTPException(status_code=422, detail="来源文章 ID 必须为正整数")
        rows = await self.reader('published', ids=[origin_article_id])
        if not rows:
            raise HTTPException(status_code=404, detail="文章不存在、已下架或无权阅读")
        article = rows[0]
        raw = article.get("content") or ""
        text = article_text(raw, int(article.get("content_type") or 1))
        budget = max_tokens if max_tokens is not None else getattr(settings, "ARTICLE_CONTEXT_MAX_TOKENS", 8192)
        if budget < 1:
            raise ValueError("文章上下文预算必须为正数")
        total_tokens = count_tokens(text)
        content = truncate_to_token_budget(text, budget)
        completeness = "full" if total_tokens <= budget else "excerpt"
        updated = article.get("update_time")
        context = {
            "article_id": str(article["article_id"]), "title": article.get("title") or "无标题",
            "content": content, "completeness": completeness,
            "full_content_tokens": total_tokens, "content_tokens": count_tokens(content),
            "source_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "updated_at": updated.isoformat() if hasattr(updated, 'isoformat') else updated,
            "url": f"/article/{article['article_id']}",
            "author_name": article.get("author_name") or "",
            "cover_image": article.get("cover_image") or "",
            "view_count": int(article.get("view_count") or 0), "like_count": int(article.get("like_count") or 0),
        }
        context["citation"] = {
            "id": "article_context:1", "articleId": context["article_id"], "title": context["title"],
            "url": context["url"], "chunkIndex": 0, "excerpt": content[:1200],
            "sourceHash": context["source_hash"],
            "chunkId": f"article_context:{context['article_id']}:{context['source_hash']}", "sectionPath": [],
        }
        return context

    @staticmethod
    def evidence(context: dict) -> dict:
        partial = context["completeness"] != "full"
        if not context["content"]:
            note = "当前文章没有可读取的文字正文；图片内容尚未解析，不能编造正文或图片信息。"
        else:
            note = ("当前文章仅提供开头节选，未读部分需要按 article_ids 检索；不得声称已经读取全文。"
                    if partial else "当前文章可见正文已完整提供。")
        return {
            "task_id": "article_context", "kind": "search", "actor": "main", "retrieval_target": "knowledge",
            "status": "succeeded", "instruction": "读取会话来源文章；来源不限制后续检索其他文章。",
            "result": f"{note}\n[article_context:1] {context['title']}\n{context['content']}",
            "citations": [context["citation"]],
            "article_cards": [{"articleId": context["article_id"], "title": context["title"],
                               "coverImage": context["cover_image"], "authorName": context["author_name"],
                               "viewCount": context["view_count"], "likeCount": context["like_count"]}],
        }


article_context_service = ArticleContextService()
