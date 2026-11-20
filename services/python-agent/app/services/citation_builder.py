"""Build citations and model context from the same verified document list."""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Citation:
    id: str
    articleId: str
    title: str
    chunkIndex: int
    excerpt: str
    sourceHash: str = ""
    chunkId: str = ""
    sectionPath: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class CitationBuilder:
    def build(self, documents: list[dict], id_prefix: str = "") -> tuple[list[Citation], str]:
        citations = []
        sections = []
        seen = set()
        for document in documents:
            article_id = str(document.get("article_id") or "")
            content = (document.get("content") or "").strip()
            chunk_index = int(document.get("chunk_index", 0))
            key = (article_id, chunk_index, content)
            if not article_id or not content or key in seen:
                continue
            seen.add(key)
            citation = Citation(
                id=f"{id_prefix}{len(citations) + 1}", articleId=article_id,
                title=document.get("title") or "无标题",
                chunkIndex=chunk_index, excerpt=content[:1200],
                sourceHash=document.get("source_hash", ""),
                chunkId=document.get("chunk_id", ""),
                sectionPath=list(document.get("section_path") or []),
            )
            citations.append(citation)
            heading = " > ".join(citation.sectionPath) or citation.title
            # Preview is bounded for the UI; the model receives the complete bounded chunk.
            sections.append(f"[{citation.id}] {heading}\n{content}")
        return citations, "\n\n".join(sections) or "未找到相关资料；不能编造平台引用。"
