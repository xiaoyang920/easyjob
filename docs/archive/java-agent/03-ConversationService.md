> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# 会话管理

## 一、数据库表

ai_conversation: conversation_id, user_id, title, message_count, status
ai_message: message_id, conversation_id, role, content, image_paths, article_cards

## 二、AiConversationService

```java
getContext(conversationId)        // 先Redis后MySQL
addMessage(...)                   // 添加消息
createConversation(userId)        // 创建会话
clearContext(conversationId)      // 删除会话
getUserConversationsWithCursor()  // 游标分页
```

## 三、Redis存储

```java
REDIS_KEY_AI_CONV = "easyjob:aiConv:"
REDIS_KEY_AI_ARTICLE_CARDS = "easyjob:aiArticleCards:"

saveConversationContext()
getConversationContext()
addArticleCards()
getAndClearArticleCards()
```

## 四、上下文截取

保留最近 maxRounds*2 条消息，system消息始终保留。
