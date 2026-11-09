"""Hold the shared admission gate until the restart parent releases stdin.

No model calls or business writes. Parent death closes stdin and releases the
transaction; a time limit also prevents an orphaned guard blocking admission.
"""
import asyncio
import json
from pathlib import Path
import sys
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python-agent'))
from app.clients.mysql_client import db
from app.services.execution_admission import ExecutionAdmission


async def main(hold_seconds=90):
    try:
        await db.connect()
        async with ExecutionAdmission(db).idle_restart():
            print(json.dumps({'status': 'ready'}), flush=True)
            command = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), hold_seconds)
            if command.strip() != 'release':
                return 2
        return 0
    except Exception as exc:
        # No SQL, credentials, user IDs or exception payloads in script output.
        print(json.dumps({'status': 'refused', 'error_type': type(exc).__name__}), flush=True)
        return 1
    finally:
        if db.is_connected:
            await db.disconnect()


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--hold-seconds',type=int,default=90);args=parser.parse_args()
    if not 30<=args.hold_seconds<=300:parser.error('hold-seconds must be 30..300')
    raise SystemExit(asyncio.run(main(args.hold_seconds)))
