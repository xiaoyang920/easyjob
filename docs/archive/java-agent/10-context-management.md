> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# 上下文管理优化：滑动窗口 + Token计数 + 对话总结

## 一、当前方案问题

当前 `AiConversationService.truncateContext()` 按固定轮数（20轮）截断，存在两个问题：

1. **粒度粗糙**：一轮对话可能是一句话，也可能是一大段，按轮数截断无法精确控制token消耗
2. **信息丢失**：超出轮数的早期对话直接丢弃，无法保留关键信息

## 二、优化方案

### 2.1 核心思路

- **Token计数**：用实际token数而非轮数来衡量上下文长度
- **滑动窗口**：历史消息总token超过阈值时，从最早的消息开始移除
- **对话总结**：被移除的消息不直接丢弃，而是用小模型压缩成摘要保留
- **前端展示与模型上下文分离**：MySQL保留所有原始消息供前端展示，模型上下文通过查询控制只加载摘要+最近N轮

### 2.2 Token阈值设计

以 DeepSeek-V3.2 128K 上下文窗口为例：

| 区域 | 占比 | Token数 | 说明 |
|------|------|---------|------|
| 历史消息 | 60% | ~76,800 | 滑动窗口控制 |
| System Prompt | 5% | ~6,400 | 固定系统提示词 |
| RAG检索结果 | 15% | ~19,200 | 动态注入 |
| Tool定义 + 图片描述 | 10% | ~12,800 | 动态 |
| 模型回复空间 | 10% | ~12,800 | 预留给输出 |

触发总结的阈值设为历史消息区域的 80%（约61,440 token），留出缓冲空间。

### 2.3 数据分离设计

**核心原则：MySQL保留完整历史，模型上下文通过查询控制**

```
MySQL（完整数据，不删除原始消息）
├── 原始消息1（user）
├── 原始消息2（assistant）
├── ...
├── 原始消息N
└── 摘要消息（system，总结触发时删旧插新，始终只有一条）

模型上下文（查询控制，只加载需要的）
├── 最新一条 system 摘要
└── 最近 N 轮 user/assistant 消息
```

- 前端展示聊天记录：查全部消息（不含 system 摘要）
- 模型上下文加载：只查最新摘要 + 最近 N 轮非 system 消息

## 三、配置项

在 `application.yml` 中新增：

```yaml
agent:
  conversation:
    # 历史消息最大token数（滑动窗口大小，128K * 60%）
    max-context-tokens: 76800
    # 触发总结的token阈值（max-context-tokens的80%）
    summarize-threshold: 61440
    # 总结后保留的最近消息轮数
    keep-recent-rounds: 5
    # 总结用的模型（用小模型降低成本）
    summary-model: deepseek-chat
```


## 四、数据库改动

### 4.1 ai_message 表新增字段

```sql
ALTER TABLE ai_message ADD COLUMN message_type VARCHAR(20) DEFAULT 'chat' COMMENT '消息类型: chat-普通消息, summary-对话摘要';
```

> 不需要改 ai_conversation 表。摘要数据完全由 ai_message 表管理，通过 message_type 区分。
> 已有数据自动为 'chat'，不影响现有功能。

### 4.2 AiMessage 实体新增

```java
// AiMessage.java 新增字段
/**
 * 消息类型: chat-普通消息, summary-对话摘要
 * 用于区分摘要和普通system消息，避免 role='system' 混淆
 */
private String messageType;
```

### 4.3 AiMessageMapper 新增查询方法

拆为两个简单查询，Java层组装。避免复杂UNION ALL，且自然处理没有摘要的情况。

```java
/**
 * 查询最新一条摘要
 */
@Select("SELECT * FROM ai_message WHERE conversation_id = #{conversationId} AND message_type = 'summary' ORDER BY create_time DESC LIMIT 1")
AiMessage selectLatestSummary(@Param("conversationId") Long conversationId);

/**
 * 查询摘要之后的chat消息（没有摘要时查全部chat）
 * 通过 afterTime 过滤，确保不会查到已被总结的旧消息
 */
@Select("""
    <script>
    SELECT * FROM ai_message 
    WHERE conversation_id = #{conversationId} AND message_type = 'chat'
    <if test="afterTime != null">
        AND create_time > #{afterTime}
    </if>
    ORDER BY create_time ASC
    </script>
    """)
List<AiMessage> selectChatMessagesAfter(@Param("conversationId") Long conversationId,
                                         @Param("afterTime") LocalDateTime afterTime);
```

## 五、核心代码改动

### 5.1 新增 TokenCounter 工具类

使用 Spring AI 内置的 `JTokkitTokenCountEstimator`（在 `spring-ai-core` 中，无需额外引入依赖）。
底层基于 OpenAI tokenizer（cl100k_base），与 DeepSeek 实际 tokenizer 有微小偏差，但作为阈值判断足够。

```java
package com.easyjob.agent.component;

import org.springframework.ai.tokenizer.JTokkitTokenCountEstimator;
import org.springframework.ai.tokenizer.TokenCountEstimator;
import org.springframework.stereotype.Component;

/**
 * Token计数器
 * 使用 Spring AI 内置的 JTokkit 估算token数（无需额外依赖）
 */
@Component
public class TokenCounter {

    private final TokenCountEstimator estimator = new JTokkitTokenCountEstimator();

    /**
     * 估算文本的token数
     */
    public int countTokens(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        return estimator.estimate(text);
    }
}
```

### 5.2 改造 AiConversationService

#### 5.2.1 新增依赖注入和配置

```java
@Autowired
private TokenCounter tokenCounter;

@Autowired
@Qualifier("summaryChatClient")
private ChatClient summaryChatClient;

@Value("${agent.conversation.max-context-tokens:76800}")
private int maxContextTokens;

@Value("${agent.conversation.summarize-threshold:61440}")
private int summarizeThreshold;

@Value("${agent.conversation.keep-recent-rounds:5}")
private int keepRecentRounds;
```

#### 5.2.2 改造 getContext 方法

```java
/**
 * 获取会话上下文（供模型使用）
 *
 * 【改动】从MySQL加载时拆为两个简单查询：摘要 + 摘要之后的chat消息
 *        读操作保持轻量，不触发总结
 */
public List<AiMessage> getContext(Long conversationId) {
    // 从Redis获取
    List<AiMessage> cached = redisComponent.getConversationContext(conversationId);
    if (cached != null) {
        log.debug("从Redis获取会话上下文: {}", conversationId);
        return cached;
    }
    // Redis没有，从MySQL加载
    List<AiMessage> messages = loadContextFromDb(conversationId);
    if (messages.isEmpty()) {
        return new ArrayList<>();
    }
    // 缓存到Redis
    redisComponent.saveConversationContext(conversationId, messages);
    log.debug("从MySQL加载会话上下文并缓存: {}", conversationId);
    return messages;
}

/**
 * 从MySQL加载模型上下文
 * 拆为两个简单查询，Java层组装，避免复杂UNION ALL
 */
private List<AiMessage> loadContextFromDb(Long conversationId) {
    // 1. 查最新一条摘要
    AiMessage summary = aiMessageMapper.selectLatestSummary(conversationId);
    
    // 2. 查摘要之后的chat消息（没有摘要时afterTime为null，查全部chat）
    LocalDateTime afterTime = summary != null ? summary.getCreateTime() : null;
    List<AiMessage> chatMsgs = aiMessageMapper.selectChatMessagesAfter(conversationId, afterTime);
    
    // 3. 组装
    List<AiMessage> result = new ArrayList<>();
    if (summary != null) {
        result.add(summary);
    }
    result.addAll(chatMsgs);
    return result;
}
```


#### 5.2.3 替换 truncateContext 为 manageContext

删除原有的 `truncateContext` 方法，替换为：

```java
/**
 * 基于Token计数的上下文管理（替代原有的轮数截断）
 *
 * 【职责】只负责裁剪/总结并返回结果，不负责写Redis
 *        Redis的写入统一由调用方（addMessage）负责
 */
private List<AiMessage> manageContext(Long conversationId, List<AiMessage> context) {
    // 1. 计算总token数
    int totalTokens = calculateTotalTokens(context);

    // 2. 未超过阈值，直接返回
    if (totalTokens <= summarizeThreshold) {
        return context;
    }

    log.info("上下文token数 {} 超过阈值 {}，触发总结, conversationId={}",
            totalTokens, summarizeThreshold, conversationId);

    // 3. 分离：摘要(summary) + 普通消息(chat)
    AiMessage oldSummary = null;
    List<AiMessage> chatMsgs = new ArrayList<>();
    for (AiMessage msg : context) {
        if ("summary".equals(msg.getMessageType())) {
            oldSummary = msg;
        } else {
            chatMsgs.add(msg);
        }
    }

    // 4. 保留最近N轮原始消息
    int keepCount = keepRecentRounds * 2;
    if (chatMsgs.size() <= keepCount) {
        return trimByToken(context);
    }
    List<AiMessage> oldMsgs = chatMsgs.subList(0, chatMsgs.size() - keepCount);
    List<AiMessage> recentMsgs = new ArrayList<>(
            chatMsgs.subList(chatMsgs.size() - keepCount, chatMsgs.size()));

    // 5. 调用小模型总结旧消息
    String newSummaryText = summarize(oldSummary, oldMsgs);
    int summaryTokens = tokenCounter.countTokens(newSummaryText);

    // 6. 构建新的上下文
    AiMessage summaryMsg = new AiMessage();
    summaryMsg.setRole("system");
    summaryMsg.setMessageType("summary");  // 通过messageType区分，而非role
    summaryMsg.setContent(newSummaryText);
    summaryMsg.setTokenCount(summaryTokens);
    summaryMsg.setConversationId(conversationId);
    summaryMsg.setCreateTime(LocalDateTime.now());

    List<AiMessage> newContext = new ArrayList<>();
    newContext.add(summaryMsg);
    newContext.addAll(recentMsgs);

    // 7. 更新MySQL：删旧摘要，插入新摘要（原始消息不删除）
    updateSummaryInDb(conversationId, oldSummary, newSummaryText, summaryTokens);

    log.info("总结完成, conversationId={}, 旧消息数={}, 摘要token数={}, 剩余消息数={}",
            conversationId, oldMsgs.size(), summaryTokens, newContext.size());

    return newContext;
}

/**
 * 计算消息列表的总token数
 */
private int calculateTotalTokens(List<AiMessage> messages) {
    int total = 0;
    for (AiMessage msg : messages) {
        if (msg.getTokenCount() != null && msg.getTokenCount() > 0) {
            total += msg.getTokenCount();
        } else {
            int tokens = tokenCounter.countTokens(msg.getContent());
            msg.setTokenCount(tokens);
            total += tokens;
        }
    }
    return total;
}
```

#### 5.2.4 总结方法

```java
/**
 * 调用小模型对旧消息进行总结
 */
private String summarize(AiMessage oldSummary, List<AiMessage> oldMsgs) {
    StringBuilder input = new StringBuilder();

    if (oldSummary != null && oldSummary.getContent() != null) {
        input.append("【之前的对话摘要】\n").append(oldSummary.getContent()).append("\n\n");
    }

    input.append("【需要总结的对话】\n");
    for (AiMessage msg : oldMsgs) {
        input.append(msg.getRole()).append(": ").append(msg.getContent()).append("\n");
    }

    String prompt = """
            请将以下对话内容压缩总结为一段简洁的摘要，要求：
            1. 保留关键信息：用户的核心问题、AI的关键结论、重要的技术细节
            2. 去除寒暄、重复内容、过渡性语句
            3. 摘要长度控制在300字以内
            4. 使用第三人称描述（"用户讨论了..."、"AI回答了..."）
            
            """ + input;

    try {
        String summary = summaryChatClient.prompt()
                .user(prompt)
                .call()
                .content();
        log.info("对话总结完成, 输入消息数={}, 摘要长度={}", oldMsgs.size(), summary.length());
        return summary;
    } catch (Exception e) {
        log.error("对话总结失败，降级为简单截断", e);
        return oldMsgs.stream()
                .skip(Math.max(0, oldMsgs.size() - 4))
                .map(msg -> msg.getRole() + ": " + msg.getContent())
                .reduce((a, b) -> a + "\n" + b)
                .orElse("");
    }
}
```


#### 5.2.5 数据库更新方法（方案C：不删原始消息）

```java
/**
 * 更新MySQL中的摘要数据
 * 【方案C】只删旧摘要 + 插新摘要，原始聊天消息不删除
 */
@Transactional
private void updateSummaryInDb(Long conversationId, AiMessage oldSummary,
                                String newSummaryText, int summaryTokens) {
    // 1. 删除旧摘要（通过messageType='summary'精确定位）
    if (oldSummary != null && oldSummary.getMessageId() != null) {
        aiMessageMapper.deleteById(oldSummary.getMessageId());
    }

    // 2. 插入新摘要消息
    AiMessage summaryMsg = new AiMessage();
    summaryMsg.setConversationId(conversationId);
    summaryMsg.setRole("system");
    summaryMsg.setMessageType("summary");  // 标记为摘要类型
    summaryMsg.setContent(newSummaryText);
    summaryMsg.setTokenCount(summaryTokens);
    summaryMsg.setCreateTime(LocalDateTime.now());
    aiMessageMapper.insert(summaryMsg);
}

/**
 * 简单按token裁剪（降级方案，不做总结）
 * 只从内存列表中移除，不删MySQL数据
 */
private List<AiMessage> trimByToken(List<AiMessage> context) {
    int totalTokens = calculateTotalTokens(context);
    List<AiMessage> result = new ArrayList<>(context);

    while (totalTokens > maxContextTokens && result.size() > 2) {
        for (int i = 0; i < result.size(); i++) {
            if (!"summary".equals(result.get(i).getMessageType())) {
                totalTokens -= result.get(i).getTokenCount();
                result.remove(i);
                break;
            }
        }
    }
    return result;
}
```

#### 5.2.6 修改 addMessage 方法

```java
public void addMessage(Long conversationId, Long userId, String role, String content,
                       List<String> imagePaths, List<ArticleCardVO> articleCards) {
    List<AiMessage> context = getContext(conversationId);

    AiMessage message = new AiMessage();
    message.setConversationId(conversationId);
    message.setRole(role);
    message.setContent(content);
    message.setImagePaths(imagePaths);
    message.setCreateTime(LocalDateTime.now());
    message.setArticleCards(articleCards);
    // 【新增】计算并缓存token数
    int tokenCount = tokenCounter.countTokens(content);
    message.setTokenCount(tokenCount);
    context.add(message);

    // 【改动】替换 truncateContext 为 manageContext（只裁剪/总结，不写Redis）
    context = manageContext(conversationId, context);

    // Redis写入统一由addMessage负责
    redisComponent.saveConversationContext(conversationId, context);
    // 【改动】传入tokenCount
    saveToMysql(conversationId, userId, role, content, imagePaths, articleCards, tokenCount);
    log.debug("添加消息到会话: {}, role={}", conversationId, role);
}
```

#### 5.2.7 改造 saveToMysql 方法

```java
/**
 * 保存消息到MySQL
 * 【改动】新增 tokenCount 参数，写入时一并保存
 */
private void saveToMysql(Long conversationId, Long userId, String role, String content,
                         List<String> imagePaths, List<ArticleCardVO> articleCards, int tokenCount) {
    AiMessage message = new AiMessage();
    message.setConversationId(conversationId);
    message.setRole(role);
    message.setContent(content);
    message.setImagePaths(imagePaths);
    message.setCreateTime(LocalDateTime.now());
    message.setArticleCards(articleCards);
    message.setTokenCount(tokenCount);
    aiMessageMapper.insert(message);

    aiConversationMapper.incrementMessageCount(conversationId);

    if ("user".equals(role)) {
        AiConversation conv = aiConversationMapper.selectById(conversationId);
        if (conv != null && conv.getTitle() == null) {
            String title = content.length() > 50 ? content.substring(0, 50) + "..." : content;
            aiConversationMapper.updateTitle(conversationId, title);
        }
    }
}
```

### 5.3 新增总结专用 ChatClient

在 `ChatClientConfiguration.java` 中新增：

```java
/**
 * 总结专用客户端（使用同一个DeepSeek模型，但系统提示词不同）
 * 如果有更便宜的小模型可以替换
 */
@Bean("summaryChatClient")
public ChatClient summaryChatClient(DeepSeekChatModel deepSeekChatModel) {
    return ChatClient.builder(deepSeekChatModel)
            .defaultSystem("你是一个对话总结助手，负责将对话内容压缩为简洁的摘要。")
            .build();
}
```

### 5.4 删除不再需要的方法

`AiConversationMapper` 中不需要新增 `updateSummary` 方法，摘要完全由 `ai_message` 表管理。

## 六、流程图

```
用户发送消息
    |
从 Redis 获取上下文（摘要 + 最近N轮）
    |
Redis 没有？-> 从 MySQL 查询（selectContextMessages：最新摘要 + 最近N轮）-> 缓存到 Redis
    |
添加当前消息到上下文，计算 tokenCount
    |
manageContext 计算总 token 数
    |
超过阈值(61440)？—— 否 -> 直接返回原上下文
    |
    是
    |
分离：旧摘要 + 旧消息 | 最近 N 轮
    |
调用小模型：旧摘要 + 旧消息 -> 生成新摘要
    |
MySQL：删旧摘要 + 插新摘要（原始消息不删除）
    |
返回新上下文：[新摘要 + 最近N轮]
    |
addMessage 统一写 Redis（整体覆盖）
    |
saveToMysql 写入当前消息（带 tokenCount）
    |
发给模型：System Prompt + RAG + 摘要 + 最近 N 条 + 当前消息
```

## 七、注意事项

1. **前端展示与模型上下文分离**：MySQL保留所有原始消息供前端展示聊天记录，模型上下文通过 `selectContextMessages` 查询控制（按 `message_type` 区分），只加载摘要+最近N轮。这与 ChatGPT 等主流产品的做法一致
2. **Token计数的准确性**：JTokkit 基于 OpenAI tokenizer 估算，与 DeepSeek 实际 tokenizer 可能有偏差，但作为阈值判断足够用
3. **总结失败降级**：小模型调用失败时，降级为按token裁剪（只从内存列表移除，不删MySQL），保证服务可用
4. **摘要的生命周期**：MySQL中同一会话只保留一条 `message_type='summary'` 的消息（每次总结删旧插新）。新摘要 = 旧摘要内容 + 新压缩的旧消息，不会丢失累积信息
5. **message_type 字段设计**：用 `message_type` 区分摘要和普通消息，而非 `role`。`role` 只负责标识角色（user/assistant/system），`message_type` 负责标识用途（chat/summary），避免以后有其他 system 消息时混淆
6. **saveToMysql 写入 tokenCount**：避免从MySQL加载时重复计算token
7. **getContext 读操作轻量**：从MySQL加载时只查询，不触发总结。总结只在 addMessage 写入新消息时触发
