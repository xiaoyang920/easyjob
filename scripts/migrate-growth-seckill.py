"""Explicit replayable upgrade. No demo activities or user balance changes."""
import asyncio, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python-agent'))
from app.clients.mysql_client import db
from app.migrate import apply_product_features

async def main():
    await db.connect()
    try:
        await apply_product_features(db,'031_growth_seckill.sql')
        print('Growth seckill schema ready; balances unchanged.')
    finally:await db.disconnect()

if __name__=='__main__':asyncio.run(main())
