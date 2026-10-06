"""Apply and replay only migration 014 on the local development database."""
import asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python-agent'))
from app.clients.mysql_client import db
from app.migrate import apply_maintenance_migration
async def main():
    assert db.url.hostname in {'localhost','127.0.0.1','::1'}
    await db.connect()
    try:
        await apply_maintenance_migration(db)
        await apply_maintenance_migration(db)
        print('014 applied and replayed; existing rows preserved.')
    finally:await db.disconnect()
if __name__=='__main__':asyncio.run(main())
