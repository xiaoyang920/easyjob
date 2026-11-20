"""Opt-in live model probe. Reads only a synthetic test-page screenshot on stdin."""
import asyncio
import json
import sys

from app.services.browser_control import locate


async def main():
    request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    point = await locate(request['image'], request['target'])
    print(json.dumps(point))
    if point is None:
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
