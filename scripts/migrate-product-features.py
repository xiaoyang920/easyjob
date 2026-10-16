"""Add conversation metadata, durable feedback and successful-message/run association."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python-agent'))
from app.clients.mysql_client import db
from app.migrate import apply_product_features

async def main():
    await db.connect()
    try:
        await apply_product_features(db)
        await apply_product_features(db,'023_draft_create_request.sql')
        print('Product feature migrations 022 and 023 applied.')
    finally:await db.disconnect()

if __name__=='__main__':asyncio.run(main())
