"""Run explicitly after backup, with writers stopped: python scripts/migrate-social.py."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'python-agent'))
from app.clients.mysql_client import db
from app.social_migration import apply_social_migration

async def main():
    await db.connect()
    try:
        await apply_social_migration(db)
        print('朋友与私信迁移完成；旧会话 ID 作为别名保留，消息未删除。')
    finally:
        await db.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
