> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# Agent核心

## 一、ChatClientConfiguration

```java
@Configuration
public class ChatClientConfiguration {
    
    @Bean
    public ChatClient chatClient(DeepSeekChatModel deepSeekChatModel) {
        return ChatClient.builder(deepSeekChatModel)
                .defaultSystem(buildSystemPrompt())
                .build();
    }
    
    @Bean("zhipuVisionClient")
    public ChatClient zhipuVisionClient(ZhiPuAiChatModel zhiPuAiChatModel) {
        return ChatClient.builder(zhiPuAiChatModel)
                .defaultSystem(ZHIPU_VISION_SYSTEM_PROMPT)
                .build();
    }
}
```

## 二、AgentService.chatStream()

```java
public Flux<String> chatStream(Long conversationId, Long userId, 
                                String userMessage, List<String> imagePaths) {
    // 1. 创建或获取会话
    // 2. 图片转文字 (ImageUnderstandingService)
    // 3. 构建历史消息 + RAG上下文
    // 4. 保存用户消息
    // 5. 流式调用AI
    return Flux.concat(
        Flux.just("__CONV_ID__:" + conversationId),
        chatClient.prompt()
            .messages(messages)
            .tools(articleTool, bochaSearchTool)
            .toolContext(Map.of("conversationId", conversationId))
            .stream()
            .content(),
        Flux.defer(() -> /* 返回文章卡片JSON */)
    );
}
```

## 三、ImageUnderstandingService

图片理解流程:
1. 读取图片文件
2. 压缩(等比缩放+JPEG降质量，目标<2MB)
3. 调用智谱GLM-4.6V-Flash(带120秒超时)
4. 返回图片描述文本

```java
private static final int MAX_IMAGE_DIMENSION = 1920;
private static final long MAX_IMAGE_BYTES = 2 * 1024 * 1024;
private static final int API_TIMEOUT_SECONDS = 120;
```

## 四、AgentController

```java
@PostMapping(value = "/chat/stream", produces = TEXT_EVENT_STREAM_VALUE)
public Flux<String> chatStream(@RequestBody AiChatParam param)

@GetMapping("/conversations")
public ResponseVO getConversations(...)

@GetMapping("/conversations/{conversationId}/messages")
public ResponseVO getMessages(...)

@DeleteMapping("/conversations/{conversationId}")
public ResponseVO deleteConversation(...)
```
