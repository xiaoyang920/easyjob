from app.config import settings
from app.services.traced_database import TracedDatabase

db = TracedDatabase(settings.mysql_url)

async def startup():
    await db.connect()

async def shutdown():
    await db.disconnect()
