"""Apply non-destructive 020 locally with applications stopped; verify replay and body preservation."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python-agent'))
from app.clients.mysql_client import db
from app.services.revision_migration import apply_revision_workspace_migration, check_revision_workspace_schema


async def snapshot():
    rows=await db.fetch_all('SELECT article_id,user_id,title,summary,content,status,deleted,required_level,published_revision_id FROM article_info ORDER BY article_id')
    text=json.dumps([dict(r._mapping) for r in rows],ensure_ascii=False,default=str,sort_keys=True)
    tags=await db.fetch_all('SELECT * FROM article_tag_relation ORDER BY article_id,tag_id')
    return len(rows),hashlib.sha256(text.encode()).hexdigest(),hashlib.sha256(json.dumps([dict(r._mapping) for r in tags],default=str,sort_keys=True).encode()).hexdigest()


async def main():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'}
    await db.connect()
    try:
        before=await snapshot()
        await apply_revision_workspace_migration(db)
        await check_revision_workspace_schema(db)
        assert before==await snapshot(),'Existing article content or associations changed'
        count=await db.fetch_val('SELECT COUNT(*) FROM article_revision')
        await apply_revision_workspace_migration(db)
        assert count==await db.fetch_val('SELECT COUNT(*) FROM article_revision')
        assert before==await snapshot()
        print(f'020 applied and replay checked; {before[0]} existing info rows, their bodies and tag relations preserved.')
    finally:
        await db.disconnect()

if __name__=='__main__':asyncio.run(main())
