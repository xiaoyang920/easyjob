"""Replayable workspace upgrade. Legacy info rows are deliberately preserved.

New drafts use revisions only. Old unpublished info rows remain compatibility
records until a separately backed-up and approved historical cleanup.
Run while application writers are stopped.
"""
import hashlib
import json
import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / 'migrations/020_revision_workspaces.sql'


async def check_revision_workspace_schema(database):
    count = await database.fetch_val("""SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema=DATABASE() AND table_name='article_revision'
        AND column_name IN ('lock_version','updated_at','deleted','is_current','data_source','required_level','current_article_id')""")
    receipt = await database.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': MIGRATION.name})
    if count != 7 or receipt != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
        raise RuntimeError('草稿工作区迁移未完成，请运行 python -m app.migrate')


async def apply_revision_workspace_migration(database):
    checksum = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    async with database.connection() as connection:
        if await connection.fetch_val("SELECT GET_LOCK('easyjob_agent_schema',10)") != 1:
            raise RuntimeError('无法取得迁移锁')
        try:
            previous = await connection.fetch_val('SELECT checksum FROM agent_schema_migration WHERE version=:v', {'v': MIGRATION.name})
            if previous:
                if previous != checksum:
                    raise RuntimeError('草稿工作区迁移校验和发生变化')
                return
            for statement in MIGRATION.read_text(encoding='utf-8').split(';'):
                statement = statement.strip()
                if not statement:
                    continue
                column = re.match(r'ALTER TABLE (\w+) ADD COLUMN (\w+) ', statement)
                index = re.match(r'CREATE (?:UNIQUE )?INDEX (\w+) ON (\w+)', statement)
                if column and await connection.fetch_val('SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:n', {'t': column[1], 'n': column[2]}):
                    continue
                if index and await connection.fetch_val('SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=:t AND index_name=:n', {'t': index[2], 'n': index[1]}):
                    continue
                await connection.execute(statement)
            async with connection.transaction():
                await connection.execute('''UPDATE article_revision r JOIN article_info a ON a.article_id=r.article_id
                    SET r.deleted=a.deleted,r.data_source=a.data_source,r.required_level=a.required_level,
                        r.updated_at=COALESCE(r.reviewed_at,r.submitted_at,r.created_at),
                        r.is_current=IF(r.revision_id=a.latest_revision_id AND a.deleted=0,1,0)''')
                rows = await connection.fetch_all('''SELECT a.* FROM article_info a
                    WHERE a.status=0 AND a.deleted=0 AND NOT EXISTS
                    (SELECT 1 FROM article_revision r WHERE r.article_id=a.article_id AND r.is_current=1)''')
                for row in rows:
                    a = dict(row._mapping)
                    tag_rows = await connection.fetch_all('''SELECT t.tag_name FROM article_tag_relation rel
                        JOIN article_tag t ON t.tag_id=rel.tag_id WHERE rel.article_id=:id''', {'id': a['article_id']})
                    names = [r._mapping['tag_name'] for r in tag_rows] or [s.strip() for s in (a.get('tags') or '').split(',') if s.strip()]
                    payload = {'title': a['title'], 'summary': a['summary'], 'content': a['content'] or '',
                        'contentType': a['content_type'], 'categoryId': str(a['category_id']) if a['category_id'] else None,
                        'coverImage': a['cover_image'], 'isOriginal': a['is_original'], 'tagNames': names}
                    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                    version = await connection.fetch_val('SELECT COALESCE(MAX(version_no),0)+1 FROM article_revision WHERE article_id=:id', {'id': a['article_id']})
                    rid = await connection.execute('''INSERT INTO article_revision(article_id,version_no,author_id,base_revision_id,state,payload,content_hash,is_current,data_source,required_level,created_at,updated_at)
                        VALUES(:id,:v,:uid,0,0,:p,:h,1,:source,:level,:created,:updated)''',
                        {'id': a['article_id'], 'v': version, 'uid': a['user_id'], 'p': text, 'h': hashlib.sha256(text.encode()).hexdigest(),
                         'source': a['data_source'], 'level': a['required_level'], 'created': a['create_time'], 'updated': a['update_time'] or a['create_time']})
                    await connection.execute('UPDATE article_info SET latest_revision_id=:rid WHERE article_id=:id', {'rid': rid, 'id': a['article_id']})
                await connection.execute('INSERT INTO agent_schema_migration(version,checksum) VALUES(:v,:c)', {'v': MIGRATION.name, 'c': checksum})
        finally:
            await connection.fetch_val("SELECT RELEASE_LOCK('easyjob_agent_schema')")
