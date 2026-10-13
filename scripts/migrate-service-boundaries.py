"""Apply only the additive service ownership migration to an initialized database."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python-agent'))
from app.clients.mysql_client import db
from app.migrate import apply_service_boundaries

async def main():
    await db.connect()
    try:
        await apply_service_boundaries(db)
        print('Service boundary migration 021 applied.')
    finally:
        await db.disconnect()

if __name__=='__main__':
    asyncio.run(main())
