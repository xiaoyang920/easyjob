> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# Tool定义

## 一、ArticleTool

```java
@Tool(description = "根据关键词搜索平台上的文章")
public String searchArticles(
    @ToolParam(description = "搜索关键词") String keyword,
    @ToolParam(description = "返回数量", required = false) Integer limit,
    ToolContext toolContext
)

@Tool(description = "语义搜索文章")
public String semanticSearch(
    @ToolParam(description = "搜索问题") String query,
    @ToolParam(description = "返回数量", required = false) Integer topK,
    ToolContext toolContext
)

@Tool(description = "获取文章详情")
public String getArticleDetail(
    @ToolParam(description = "文章ID") Long articleId
)
```

## 二、BochaSearchTool

```java
@Tool(description = "联网搜索，获取实时信息")
public String webSearch(
    @ToolParam(description = "搜索关键词") String query,
    @ToolParam(description = "时效性: day/week/month/year") String freshness
)
```

## 三、跨线程问题解决

Spring AI Tool在boundedElastic线程池执行，ThreadLocal无法传递数据。

解决方案: ToolContext + Redis

```java
// AgentService传递会话ID
chatClient.prompt()
    .tools(articleTool, bochaSearchTool)
    .toolContext(Map.of("conversationId", conversationId))
    .stream()

// Tool中获取
Long conversationId = (Long) toolContext.getContext().get("conversationId");
redisComponent.addArticleCards(conversationId, cards);
```
