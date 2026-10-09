"""Bootstrap only a fresh disposable CI database from schema-only DDL."""
import os,asyncio
from pathlib import Path
from app.clients.mysql_client import db
def statements(ddl):
    """Keep semicolons inside SQL string comments/defaults intact."""
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
async def main():
    assert os.getenv('EASYJOB_CI')=='1' and db.url.database.endswith('_ci'),'Disposable *_ci database required'
    await db.connect()
    try:
        assert not await db.fetch_all('SHOW TABLES'),'CI database must be empty'
        ddl=(Path(__file__).resolve().parents[2]/'tests/integration/schema.sql').read_text(encoding='utf-8')
        ddl='\n'.join(line for line in ddl.splitlines() if not line.lstrip().startswith('--'))
        # DDL contains literal ':name' in comments; do not pass it through a bind parser.
        async with db.connection() as connection:
            async with connection.raw_connection.cursor() as cursor:
                for sql in statements(ddl):await cursor.execute(sql)
    finally:await db.disconnect()
if __name__=='__main__':asyncio.run(main())
