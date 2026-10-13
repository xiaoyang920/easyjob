"""CI peer: real Agent-owned SQL queries, no workers, model calls or chat simulation."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'python-agent'))
from app.clients.mysql_client import db
from app.rpc.server import start_server
from app.rpc.discovery import catalog

async def main():
    await db.connect()
    server=await start_server(SimpleNamespace())
    await catalog.start()
    print('Agent query peer ready',flush=True)
    try:
        await server.wait_for_termination()
    finally:
        await catalog.close()
        await server.stop(0)
        await db.disconnect()

if __name__=='__main__':
    asyncio.run(main())
