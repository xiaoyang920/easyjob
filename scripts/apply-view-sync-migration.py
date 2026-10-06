"""Apply only the durable view counter migration on the local development DB."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python-agent'))
from app.clients.mysql_client import db
from app.migrate import apply_view_sync_migration

async def main():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'}
    await db.connect()
    try:
        await apply_view_sync_migration(db)
        await apply_view_sync_migration(db)
        print('013 applied; replay preserved existing data.')
    finally: await db.disconnect()

if __name__=='__main__': asyncio.run(main())
