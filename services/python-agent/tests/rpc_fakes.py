"""Explicit RPC stand-ins for tests whose boundary predates service separation."""
from unittest.mock import AsyncMock


def public_reader(database):
    async def read(kind, **values):
        rows = await database.fetch_all(kind, values)
        return [dict(r._mapping) if hasattr(r, '_mapping') else dict(r) for r in rows]
    return AsyncMock(side_effect=read)
