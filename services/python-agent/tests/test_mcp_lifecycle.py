import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.clients.mcp_client import McpClientManager


class McpLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_does_not_use_unsupported_context_manager(self):
        manager = McpClientManager()
        client = SimpleNamespace(__aexit__=AsyncMock(side_effect=NotImplementedError))
        manager._client = client
        manager._tools = [object()]
        await manager.shutdown()
        await manager.shutdown()
        client.__aexit__.assert_not_awaited()
        self.assertEqual(manager.get_tools(), [])
        self.assertIsNone(manager._client)

    async def test_failed_discovery_preserves_previously_loaded_client_and_tools(self):
        manager = McpClientManager()
        previous_client, previous_tools = manager._client, [object()]
        manager._tools = previous_tools
        failed = SimpleNamespace(get_tools=AsyncMock(side_effect=RuntimeError("discovery failed")))
        with patch("app.clients.mcp_client.MultiServerMCPClient", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "discovery failed"):
                await manager.connect({"test": {"transport": "stdio"}})
        self.assertIs(manager._client, previous_client)
        self.assertIs(manager.get_tools(), previous_tools)


if __name__ == "__main__":
    unittest.main()
