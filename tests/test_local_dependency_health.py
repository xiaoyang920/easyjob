"""Offline regression for launcher dependency checks; no services or model calls."""
import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

source = Path(__file__).resolve().parents[1] / "scripts/local-dependency-health.py"
spec = importlib.util.spec_from_file_location("local_dependency_health", source)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class DependencyHealthTests(unittest.TestCase):
    def test_cache_redis_only_requires_ping_and_always_closes(self):
        client = MagicMock()
        with patch.object(health, "Redis", return_value=client):
            health.check_redis("REDIS_", 6379)
        client.ping.assert_called_once()
        client.module_list.assert_not_called()
        client.close.assert_called_once()

    def test_checkpoint_accepts_both_modules(self):
        client = MagicMock()
        client.module_list.return_value = [{"name": "search"}, {"name": "ReJSON"}]
        with patch.object(health, "Redis", return_value=client):
            health.check_redis("REDIS_STACK_", 6380, modules=True)
        client.close.assert_called_once()

    def test_plain_redis_cannot_pretend_checkpoint_is_ready(self):
        client = MagicMock()
        client.module_list.return_value = [{"name": "search"}]
        with patch.object(health, "Redis", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "RedisJSON"):
                health.check_redis("REDIS_STACK_", 6380, modules=True)
        client.close.assert_called_once()

    def test_failed_ping_still_closes_client(self):
        client = MagicMock()
        client.ping.side_effect = OSError("offline")
        with patch.object(health, "Redis", return_value=client):
            with self.assertRaises(OSError):
                health.check_redis("REDIS_", 6379)
        client.close.assert_called_once()

    def test_mysql_probe_only_reads_and_closes_connection(self):
        connection, cursor = MagicMock(), AsyncMock()
        connection.cursor.return_value.__aenter__.return_value = cursor
        cursor.fetchone.return_value = (1,)
        with patch.object(health.aiomysql, "connect", new=AsyncMock(return_value=connection)):
            asyncio.run(health.check_mysql())
        cursor.execute.assert_awaited_once_with("SELECT 1")
        connection.close.assert_called_once()

    def test_connector_error_message_does_not_expose_credentials(self):
        output = io.StringIO()
        with patch.object(health, "check_mysql", new=AsyncMock(side_effect=ValueError("password=private-sentinel"))):
            with contextlib.redirect_stdout(output):
                self.assertEqual(1, health.main())
        self.assertIn("MySQL readiness failed", output.getvalue())
        self.assertNotIn("private-sentinel", output.getvalue())


if __name__ == "__main__":
    unittest.main()
