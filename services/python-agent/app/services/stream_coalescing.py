"""Merge only provisional text deltas; barriers and first text flush immediately."""
import asyncio
import json
import time


def preview_delta(frame):
    prefix = 'data:__PREVIEW__:'
    if not frame.startswith(prefix):
        return None
    try:
        value = json.loads(frame[len(prefix):].strip())
    except (TypeError, ValueError):
        return None
    if value.get('type') == 'delta' and value.get('provisional') is True and isinstance(value.get('content'), str):
        return value
    return None


async def coalesce_previews(source, interval=.12, max_chars=4096):
    pending, pieces, started, first = None, [], 0., True
    def flush():
        frame = 'data:__PREVIEW__:' + json.dumps({'type': 'delta', 'content': ''.join(pieces),
                    'provisional': True}, ensure_ascii=False) + '\n\n'
        pieces.clear()
        return frame
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(source))
            timeout = max(0., interval - (time.monotonic() - started)) if pieces else None
            done, _ = await asyncio.wait([pending], timeout=timeout)
            if not done:
                yield flush()
                continue
            try:
                frame = pending.result()
            except StopAsyncIteration:
                pending = None
                if pieces:
                    yield flush()
                break
            pending = None
            delta = preview_delta(frame)
            if delta is None or first:
                if pieces:
                    yield flush()
                if delta is not None or frame.startswith('data:__PREVIEW__:'):
                    first = False
                yield frame
            else:
                if not pieces:
                    started = time.monotonic()
                pieces.append(delta['content'])
                if sum(map(len, pieces)) >= max_chars:
                    yield flush()
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

