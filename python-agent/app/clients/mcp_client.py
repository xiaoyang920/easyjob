import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

log = logging.getLogger(__name__)
class McpClientManager:
    """
       封装 MultiServerMCPClient，管理生命周期 + 缓存工具列表

       用法:
           manager = McpClientManager()
           await manager.connect(server_configs)
           tools = manager.get_tools()        # → list[BaseTool], 直接给 bind_tools()
           await manager.shutdown()
    """
    def __init__(self):
        self._client = MultiServerMCPClient()
        self._tools: list[BaseTool] = []
    async def connect(self, server_configs: dict):
        """
                连接所有 MCP Server 并缓存工具列表

                :param server_configs: MultiServerMCPClient 的配置字典，格式:
                    {
                        "github": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-github"],
                            "transport": "stdio",
                            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
                        },
                        "weather": {
                            "url": "http://localhost:8000/mcp",
                            "transport": "http",
                        },
                    }
                """
        if not server_configs:
            log.info("无 MCP Server 配置，跳过")
            return
        self._client = MultiServerMCPClient(server_configs)
        # get_tools() 内部会自动: 连接 → initialize → list_tools → 转 LangChain Tool
        self._tools = await self._client.get_tools()
        log.info(
            "MCP 已连接 %d 个 Server，共发现 %d 个工具: %s",
            len(server_configs),
            len(self._tools),
            [t.name for t in self._tools]
        )

    def get_tools(self) -> list[BaseTool]:
        """获取所有 MCP 工具（已经是 LangChain BaseTool，可直接 bind_tools）"""
        return self._tools
    async def reload(self, server_configs: dict):
        """
                热重载: 关闭旧连接 → 用新配置重新连接

                调用时机: POST /mcp/reload 接口，运行时改配置不用重启服务
                """
        log.info("MCP 热重载开始，关闭旧连接")
        await self.shutdown()
        await self.connect(server_configs)
        log.info("MCP 热重载完成")
    async def shutdown(self):
        """关闭所有 MCP 连接"""
        if self._client:
            await self._client.__aexit__(None, None, None)
        self._tools.clear()
        self._client = None
        log.info("MCP 连接已关闭")

mcp_manager = McpClientManager()