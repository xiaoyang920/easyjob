"""Replaying the message capacity upgrade must preserve column properties."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app import migrate


def row(**values):
    return SimpleNamespace(_mapping=values)


class ContentCapacityTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, **overrides):
        column = {'type': 'text', 'nullable': 'YES', 'default_value': None,
                  'collation': 'utf8mb4_unicode_ci', 'comment': "消息正文 ' 保留", 'extra': ''}
        column.update(overrides)
        receipt = {}
        async def fetch_one(sql, params=None):
            if 'information_schema' in sql:
                return row(**column)
            return row(checksum=receipt['checksum']) if receipt else None
        async def execute(sql, params=None):
            if sql.startswith('ALTER TABLE'):
                column['type'] = 'mediumtext'
            if sql.startswith('INSERT IGNORE'):
                receipt.update(params)
        connection = SimpleNamespace(fetch_val=AsyncMock(return_value=1), fetch_one=AsyncMock(side_effect=fetch_one),
            fetch_all=AsyncMock(side_effect=lambda sql: [row(name='content', type=column['type'])]),
            execute=AsyncMock(side_effect=execute))
        @asynccontextmanager
        async def connect():
            yield connection
        return SimpleNamespace(connection=connect), connection, column, receipt

    async def test_upgrade_preserves_attributes_and_replay_does_not_alter_again(self):
        for nullable in ('YES', 'NO'):
            database, connection, column, _ = self.fixture(nullable=nullable)
            await migrate.apply_content_migration(database)
            await migrate.apply_content_migration(database)
            alters = [call for call in connection.execute.call_args_list if call.args[0].startswith('ALTER TABLE')]
            self.assertEqual(len(alters), 1)
            self.assertIn('COLLATE utf8mb4_unicode_ci', alters[0].args[0])
            self.assertIn(' NOT NULL ' if nullable == 'NO' else ' NULL ', alters[0].args[0])
            self.assertEqual(alters[0].args[1]['comment'], column['comment'])
            self.assertEqual(connection.fetch_val.await_count, 4)

    async def test_larger_existing_column_is_never_shrunk(self):
        database, connection, column, _ = self.fixture(type='longtext')
        await migrate.apply_content_migration(database)
        self.assertEqual(column['type'], 'longtext')
        self.assertFalse(any(call.args[0].startswith('ALTER TABLE') for call in connection.execute.call_args_list))

    async def test_changed_receipt_is_rejected_before_any_schema_write(self):
        database, connection, _, receipt = self.fixture()
        receipt['checksum'] = 'modified'
        with self.assertRaisesRegex(RuntimeError, '校验和'):
            await migrate.apply_content_migration(database)
        connection.execute.assert_not_awaited()
        self.assertIn('RELEASE_LOCK', connection.fetch_val.call_args.args[0])

    async def test_unknown_or_special_column_definition_is_not_overwritten(self):
        for overrides in ({'type': 'varchar'}, {'extra': 'DEFAULT_GENERATED'},
                          {'default_value': 'special'}, {'collation': 'invalid; ddl'}):
            database, connection, _, _ = self.fixture(**overrides)
            with self.assertRaises(RuntimeError):
                await migrate.apply_content_migration(database)
            connection.execute.assert_not_awaited()

    async def test_missing_lock_does_not_attempt_upgrade_or_release(self):
        database, connection, _, _ = self.fixture()
        connection.fetch_val.return_value = 0
        with self.assertRaisesRegex(RuntimeError, '迁移锁'):
            await migrate.apply_content_migration(database)
        connection.execute.assert_not_awaited()
        self.assertEqual(connection.fetch_val.await_count, 1)

    async def test_startup_capacity_check_is_read_only(self):
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[row(name='content', type='text')]), execute=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, '容量不足'):
            await migrate.check_content_schema(database)
        database.fetch_all.return_value = [row(name='content', type='mediumtext')]
        await migrate.check_content_schema(database)
        database.execute.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
