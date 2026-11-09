> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# MCP客户端

## 一、MCP协议

MCP (Model Context Protocol) 是Anthropic提出的标准化协议，用于AI与外部工具通信。

| 方式 | 适用场景 |
|------|---------|
| @Tool注解 | 内部功能，简单高效 |
| MCP协议 | 外部服务，标准化解耦 |

## 二、依赖

```xml
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-mcp-client</artifactId>
</dependency>
```

## 三、STDIO配置

```yaml
spring:
  ai:
    mcp:
      client:
        enabled: true
        type: SYNC
        stdio:
          connections:
            filesystem:
              command: npx
              args:
                - "@modelcontextprotocol/server-filesystem"
                - "D:/projects/easyjob"
```

## 四、SSE配置

```yaml
spring:
  ai:
    mcp:
      client:
        enabled: true
        sse:
          connections:
            my-server:
              url: http://localhost:3000
              sse-endpoint: /sse
```

## 五、使用

```java
@Autowired(required = false)
List<ToolCallback> mcpToolCallbacks;

chatClient.prompt()
    .tools(articleTool)
    .toolCallbacks(mcpToolCallbacks)
    .call()
```
