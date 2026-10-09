import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.migrate import apply_admin_user_migration


class AdminUserMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_migration_adds_only_missing_columns(self):
        @asynccontextmanager
        async def connection():
            yield database
        database = SimpleNamespace(connection=connection, fetch_val=AsyncMock(side_effect=[1, None, 1, 0, 0, 1]), execute=AsyncMock())
        await apply_admin_user_migration(database)
        sql = [call.args[0] for call in database.execute.call_args_list]
        self.assertFalse(any('ADD COLUMN auth_version' in s for s in sql))
        self.assertTrue(any('ADD COLUMN reason' in s for s in sql))
        self.assertTrue(any('ADD COLUMN details_json' in s for s in sql))
        self.assertTrue(any('INSERT IGNORE' in s for s in sql))
        self.assertIn('RELEASE_LOCK', database.fetch_val.call_args.args[0])

    async def test_tampered_migration_is_rejected_and_unlocks(self):
        @asynccontextmanager
        async def connection():
            yield database
        database = SimpleNamespace(connection=connection, fetch_val=AsyncMock(side_effect=[1, 'changed', 1]), execute=AsyncMock())
        with self.assertRaises(RuntimeError):
            await apply_admin_user_migration(database)
        database.execute.assert_not_awaited()
        self.assertIn('RELEASE_LOCK', database.fetch_val.call_args.args[0])
