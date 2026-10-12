"""Keyset windows of complete turns, with a separate lightweight question index."""
import json
from fastapi import HTTPException
from app.clients.mysql_client import db
from app.services.run_history import run_history
from app.services.run_repository import run_repository


class HistoryPages:
    def __init__(self, database=db, runs=run_history, repository=run_repository):
        self.db, self.runs, self.repository = database, runs, repository

    async def users(self, cid, limit, operator=None, cursor=None, descending=True, ceiling=None):
        condition = f' AND message_id {operator} :cursor' if operator else ''
        if ceiling is not None:
            condition += ' AND message_id<=:ceiling'
        rows = await self.db.fetch_all(f'''SELECT message_id FROM ai_message
            WHERE conversation_id=:cid AND role='user' {condition}
            ORDER BY message_id {'DESC' if descending else 'ASC'} LIMIT :lim''',
            {'cid': cid, 'lim': limit, **({'cursor': cursor} if operator else {}),
             **({'ceiling': ceiling} if ceiling is not None else {})})
        return [int(r._mapping['message_id']) for r in rows]

    async def page(self, cid, uid, limit=20, before=None, after=None, around=None):
        if sum(value is not None for value in (before, after, around)) > 1:
            raise HTTPException(422, '历史分页只能指定一个方向')
        # Freeze this page's upper edge. A concurrent new turn must not enter the
        # body query after the cursor and hasNewer flags have already been chosen.
        ceiling = await self.db.fetch_val('SELECT MAX(message_id) FROM ai_message WHERE conversation_id=:cid', {'cid': cid}) or 0
        if around is not None:
            if not await self.db.fetch_val("SELECT message_id FROM ai_message WHERE conversation_id=:cid AND message_id=:mid AND role='user'",
                                           {'cid': cid, 'mid': around}):
                raise HTTPException(404, '提问不存在或不属于当前会话')
            left = await self.users(cid, limit // 2 + 1, '<=', around, ceiling=ceiling)
            right = await self.users(cid, limit - len(left), '>', around, False, ceiling=ceiling)
            ids = sorted([*left, *right])
        elif after is not None:
            ids = await self.users(cid, limit, '>', after, False, ceiling=ceiling)
        else:
            ids = sorted(await self.users(cid, limit, '<' if before is not None else None, before, ceiling=ceiling))
        if not ids:
            # Legacy assistant-only conversations and an empty new conversation.
            if any(value is not None for value in (before, after, around)):
                return self.envelope([], None, None, False, False)
            rows = await self.db.fetch_all('''SELECT * FROM ai_message WHERE conversation_id=:cid AND message_id<=:ceiling
                ORDER BY message_id DESC LIMIT :lim''', {'cid': cid, 'lim': limit, 'ceiling': ceiling})
            messages = [self.message(r._mapping) for r in reversed(rows)]
            return await self.finish(cid, uid, messages, [], False, False)
        following = await self.users(cid, 1, '>', ids[-1], False, ceiling=ceiling)
        condition = ' AND message_id < :end' if following else ''
        rows = await self.db.fetch_all(f'''SELECT message_id,role,content,token_count,image_paths,
            article_cards,draft_article_id,citations,create_time FROM ai_message
            WHERE conversation_id=:cid AND message_id>=:start AND message_id<=:ceiling {condition} ORDER BY message_id''',
            {'cid': cid, 'start': ids[0], 'ceiling': ceiling, **({'end': following[0]} if following else {})})
        messages = [self.message(r._mapping) for r in rows]
        older = bool(await self.users(cid, 1, '<', ids[0], ceiling=ceiling))
        return await self.finish(cid, uid, messages, ids, older, bool(following))

    async def finish(self, cid, uid, messages, ids, older, newer):
        if ids:
            messages = await self.runs.history(cid, uid, messages, turn_ids=ids)
        if not newer:
            pending = await self.repository.pending_approval(cid)
            if pending:
                messages.append({'role': 'assistant', 'content': pending['draft'], 'runId': pending['runId'],
                    'interrupted': True, 'interruptPayload': pending, 'isDraft': True})
        turn = None
        for item in messages:
            if item['role'] == 'user':
                turn = item['messageId']
            item['turnId'] = turn
            item['itemId'] = ('message:' + item['messageId']) if item.get('messageId') else 'run:' + item['runId']
        return self.envelope(messages, str(ids[0]) if ids else None, str(ids[-1]) if ids else None, older, newer)

    @staticmethod
    def envelope(items, before, after, older, newer):
        return {'items': items, 'beforeCursor': before, 'afterCursor': after, 'hasOlder': older, 'hasNewer': newer}

    @staticmethod
    def message(row):
        row = dict(row)
        def decoded(key):
            raw = row.get(key)
            return json.loads(raw) if isinstance(raw, str) else raw
        return {'messageId': str(row['message_id']), 'role': row['role'], 'content': row['content'],
                'imagePaths': decoded('image_paths'), 'articleCards': decoded('article_cards'),
                'citations': decoded('citations'), 'draftArticleId': str(row['draft_article_id']) if row.get('draft_article_id') else None,
                'createTime': str(row['create_time']) if row.get('create_time') else None}

    async def questions(self, cid, after=None, limit=200, snapshot=None):
        if snapshot is None:
            snapshot = await self.db.fetch_val("SELECT MAX(message_id) FROM ai_message WHERE conversation_id=:cid AND role='user'", {'cid': cid})
        if not snapshot:
            return {'items': [], 'hasMore': False, 'nextCursor': None, 'snapshot': None}
        rows = await self.db.fetch_all('''WITH questions AS (
            SELECT message_id,LEAD(message_id) OVER (ORDER BY message_id) AS next_id
            FROM ai_message WHERE conversation_id=:cid AND role='user')
            SELECT CAST(q.message_id AS CHAR) AS messageId,LEFT(m.content,256) AS question,
                JSON_LENGTH(m.image_paths)>0 AS hasImage,
                (SELECT LEFT(a.content,384) FROM ai_message a WHERE a.conversation_id=:cid AND a.role='assistant'
                 AND a.message_id>q.message_id AND (q.next_id IS NULL OR a.message_id<q.next_id)
                 AND LENGTH(TRIM(a.content))>0 ORDER BY a.message_id LIMIT 1) AS answer
            FROM questions q JOIN ai_message m ON m.message_id=q.message_id
            WHERE q.message_id>:after AND q.message_id<=:snapshot ORDER BY q.message_id LIMIT :lim''',
            {'cid': cid, 'snapshot': snapshot, 'after': after or 0, 'lim': limit + 1})
        items = [{**dict(row._mapping), 'hasImage': bool(row._mapping['hasImage'])} for row in rows[:limit]]
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextCursor': items[-1]['messageId'] if items else None, 'snapshot': str(snapshot)}


history_pages = HistoryPages()
