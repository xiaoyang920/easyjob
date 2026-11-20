"""Private writing metadata. Association never grants access to article content."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.rpc.blog_client import writing_metadata, ServiceError
import json


def writing_question_title(content):
    marker = '\n\n<easyjob-writing-reference>\n'
    start = content.rfind(marker)
    if start >= 0 and content.endswith('\n</easyjob-writing-reference>'):
        try:
            reference = json.loads(content[start + len(marker):-len('\n</easyjob-writing-reference>')])
            if reference.get('version') in (1, 2):
                content = content[:start].strip() or '写作对话'
        except (ValueError, AttributeError):
            pass
    return content[:50] + '...' if len(content) > 50 else content


class WritingContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    article_id: int | None = Field(default=None, gt=0, lt=2**63)

    @field_validator('article_id', mode='before')
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError('草稿 ID 无效')
        return value


async def require_writing_article(user_id, article_id):
    if article_id is None:
        return None
    try:
        rows = await writing_metadata(user_id, [article_id])
    except ServiceError as exc:
        raise HTTPException(exc.status, '暂时无法核验写作草稿') from None
    row = next((row for row in rows if int(row['article_id']) == article_id), None)
    if not row:
        raise HTTPException(404, '草稿不存在或无权访问')
    return row


async def bind_writing(conversation_id, user_id, context: WritingContext, database=db):
    # Owner is checked before looking up any private article metadata.
    row = await database.fetch_one('SELECT origin_article_id,is_writing,writing_article_id FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid AND status=1', {'cid': conversation_id, 'uid': user_id})
    if not row:
        raise HTTPException(404, '会话不存在或无权访问')
    article = await require_writing_article(user_id, context.article_id)
    async with database.transaction():
        row = await database.fetch_one('SELECT origin_article_id,is_writing,writing_article_id,title,metadata_version FROM ai_conversation WHERE conversation_id=:cid AND user_id=:uid AND status=1 FOR UPDATE', {'cid': conversation_id, 'uid': user_id})
        if not row:
            raise HTTPException(404, '会话不存在或无权访问')
        row = dict(row._mapping)
        existing = row.get('writing_article_id')
        if row.get('origin_article_id') is not None or (existing is not None and int(existing) != context.article_id):
            raise HTTPException(409, '会话已关联其他文章，请开启新话题')
        if not row.get('is_writing') and not row.get('metadata_version') and '<ea' in (row.get('title') or ''):
            first = await database.fetch_one("SELECT content FROM ai_message WHERE conversation_id=:cid AND role='user' ORDER BY message_id LIMIT 1", {'cid': conversation_id})
            if first:
                title = writing_question_title(first._mapping['content'])
                await database.execute('UPDATE ai_conversation SET title=:title WHERE conversation_id=:cid AND user_id=:uid AND metadata_version=0', {'title': title, 'cid': conversation_id, 'uid': user_id})
        await database.execute('UPDATE ai_conversation SET is_writing=1,writing_article_id=:aid WHERE conversation_id=:cid AND user_id=:uid AND status=1', {'cid': conversation_id, 'uid': user_id, 'aid': context.article_id})
    return {'isWriting': True, 'writingArticleId': str(context.article_id) if context.article_id else None,
            'writingArticleTitle': article['title'] if article else None, 'writingArticleAvailable': article is not None}
