from app.clients.mysql_client import db
from app.rpc.blog_client import public_read
from app.services.query_rewrite import QueryFilters, ResolvedFilters


class FilterResolutionError(ValueError):
    """An explicit scope could not be resolved; do not silently broaden it."""


class FilterResolver:
    def __init__(self):
        self.reader = public_read
    async def resolve(self,filters: QueryFilters)->ResolvedFilters:
        resolved_tags, tag_soft_terms = await self._resolve_tags(filters.tags)
        category_ids, category_soft_terms = await self._find_category_ids(filters.category_names)
        author_ids, author_soft_terms = await self._find_author_ids(filters.author_name)
        required_tags, missing_tags = await self._resolve_tags(filters.required_tags)
        if category_soft_terms or author_soft_terms or missing_tags:
            raise FilterResolutionError("作者、分类或指定标签无法唯一匹配，请确认名称后重试；未扩大检索范围。")

        soft_terms = [*tag_soft_terms, *category_soft_terms, *author_soft_terms]
        return ResolvedFilters(
            tags=resolved_tags,
            required_tags=list(dict.fromkeys(required_tags)),
            time_range=filters.time_range,
            category_ids=category_ids,
            author_ids=author_ids,
            soft_terms=soft_terms
        )
    async def _resolve_tags(self,tags: list[str])->tuple[list[str], list[str]]:
        """把用户词汇规范化成 article_tag.tag_name 里真实存在的 canonical tag。"""
        if not tags:
            return [], []
        rows = await self.reader('tags', names=tags)
        matched = {str(r["tag_name"]) for r in rows}
        canonical = [tag for tag in tags if tag in matched]
        unmatched = [tag for tag in tags if tag not in matched]
        return canonical, unmatched
    async def _find_category_ids(self,category_names: list[str])-> tuple[list[int], list[str]]:
        """只接受能稳定解析成唯一 category_id 的分类名。"""
        if not category_names:
            return [], []
        rows = await self.reader('categories', names=category_names)
        matched = {}
        for row in rows:
            matched.setdefault(str(row["category_name"]), []).append(int(row["category_id"]))
        ids = [matched[name][0] for name in category_names if len(matched.get(name, [])) == 1]
        soft_terms = [name for name in category_names if len(matched.get(name, [])) != 1]
        return ids, soft_terms

    async def _find_author_ids(self, author_name: str | None) -> tuple[list[int], list[str]]:
        """昵称必须唯一命中；空结果或重名都降级成 soft_terms。"""
        if not author_name:
            return [], []

        rows = await self.reader('authors', name=author_name)
        if len(rows) != 1:
            return [], [author_name]
        return [int(rows[0]["user_id"])], []
    @staticmethod
    def _in_params(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
        placeholders = ", ".join(f":{prefix}{i}" for i in range(len(values)))
        params = {f"{prefix}{i}": value for i, value in enumerate(values)}
        return placeholders, params
