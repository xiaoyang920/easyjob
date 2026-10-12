"""Read-only admission check before restarting the local Agent process."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
from app.clients.mysql_client import db


async def main():
    try:
        await db.connect()
        count = await db.fetch_val("SELECT COUNT(*) FROM agent_run WHERE status IN ('running','queued')")
        print(json.dumps({'active_runs': count}))
        return 0 if not count else 1
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__}))
        return 2
    finally:
        if db.is_connected:
            await db.disconnect()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
