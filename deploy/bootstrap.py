"""Fresh schema bootstrap and idempotent migrations; never recreates existing tables."""
import asyncio
from pathlib import Path
from app.clients.mysql_client import db

def statements(ddl):
    buffer=[];quote=None;escaped=False
    for char in ddl:
        if quote:
            buffer.append(char)
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in "'\"`":quote=char;buffer.append(char)
        elif char==';':
            value=''.join(buffer).strip();buffer=[]
            if value:yield value
        else:buffer.append(char)
    if ''.join(buffer).strip():yield ''.join(buffer).strip()

async def bootstrap():
    await db.connect()
    try:
        if not await db.fetch_all('SHOW TABLES'):
            ddl='\n'.join(line for line in Path('/app/schema.sql').read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('--'))
            async with db.connection() as connection:
                async with connection.raw_connection.cursor() as cursor:
                    for sql in statements(ddl):await cursor.execute(sql)
    finally:await db.disconnect()
    from app.migrate import main
    await main()

if __name__=='__main__':asyncio.run(bootstrap())
