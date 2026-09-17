from databases import Database
from app.config import settings

db = Database(settings.mysql_url)

async def startup():
    await db.connect()

async def shutdown():
    await db.disconnect()