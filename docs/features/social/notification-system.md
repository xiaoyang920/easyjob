# 消息通知系统实现方案

## 一、架构

```
用户操作（评论/回复/点赞/收藏/关注/评论点赞）
    ↓
业务 Service（NotificationService.send(msg) → 写表 + 发 MQ）
    ↓
RabbitMQ 通知队列（notification.push）
    ↓
MQ 消费者（NotificationListener）
    ├── 在线用户 → SSE 实时推送（前端铃铛红点 + 列表刷新）
    └── 离线用户 → 下次登录通过 /unread 拉取
```

**推拉结合**：
- **推**：在线用户通过 SSE 实时收到通知
- **拉**：前端首次连接 / 断线重连时，调 `/unread-count` 和 `/unread` 对齐状态
- 以 `notification` 表作为持久化事实源，"推"只是锦上添花

## 二、数据库

**通知表为"事件快照"**：所有展示所需字段都冗余进表，列表查询走单表索引，不 join 其他业务表。

```sql
CREATE TABLE notification (
    notification_id BIGINT PRIMARY KEY COMMENT '雪花ID',
    user_id         BIGINT       NOT NULL COMMENT '接收者',
    sender_id       BIGINT       NOT NULL COMMENT '触发者',
    sender_nickname VARCHAR(64)  COMMENT '触发者昵称（冗余快照）',
    sender_avatar   VARCHAR(255) COMMENT '触发者头像（冗余快照）',
    type            TINYINT      NOT NULL COMMENT '1评论/回复 2点赞 3收藏 4关注 5系统',
    article_id      BIGINT       COMMENT '关联文章ID（关注类为 null）',
    article_title   VARCHAR(200) COMMENT '文章标题（冗余快照）',
    target_id       BIGINT       COMMENT '目标对象ID（评论ID/文章ID/被关注者ID）',
    target_preview  VARCHAR(200) COMMENT '目标内容预览（评论前100字，非评论类为 null）',
    content         VARCHAR(100) COMMENT '动词文案，如 "赞了你的评论"',
    is_read         TINYINT      DEFAULT 0 COMMENT '0未读 1已读',
    create_time     DATETIME     NOT NULL,
    INDEX idx_user_read (user_id, is_read, create_time DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通知表';
```

**字段设计说明**：
- `article_id`：前端点击通知跳转用，跳到文章详情
- `target_id` + `target_preview`：定位并预览被操作对象（评论ID + 评论前 100 字）
- `content` 只存**动词短语**（如 `"赞了你的评论"`），昵称由前端用 `sender_nickname` + content 自行拼接渲染，便于前端自定义样式（昵称加粗/点击跳转主页等）

## 三、通知类型枚举

`src/main/java/com/easyjob/enums/NotificationTypeEnum.java`

```java
@Getter
public enum NotificationTypeEnum {
    COMMENT_REPLY(1, "评论/回复"),
    LIKE(2, "点赞"),
    COLLECT(3, "收藏"),
    FOLLOW(4, "关注"),
    SYSTEM(5, "系统");

    private final Integer code;
    private final String desc;
    // ...
}
```

## 四、RabbitMQ

`RabbitMqConstants`：

```java
public static final String QUEUE_NOTIFICATION = "notification.push";
public static final String ROUTING_KEY_NOTIFICATION = "notification.#";
```

`RabbitMqConfig`：

```java
@Bean
public Queue notificationQueue() { return new Queue(QUEUE_NOTIFICATION, true); }

@Bean
public Binding notificationBinding(Queue notificationQueue, TopicExchange topicExchange) {
    return BindingBuilder.bind(notificationQueue).to(topicExchange)
            .with(ROUTING_KEY_NOTIFICATION);
}
```

## 五、实体 / DTO / Mapper

**实体**：`entity/Notification.java`（11 个字段，与 DDL 一一对应）

**MQ + 入参 DTO**：`dto/NotificationMessage.java`

`NotificationMessage` 既作为 `send()` 的入参（业务方用 `@Builder` 按需填），也作为 MQ 队列的消息体。复用一个对象避免两边字段漂移。

```java
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class NotificationMessage implements Serializable {
    private Long notificationId;
    private Long userId;           // 接收者
    private Long senderId;         // 触发者
    private String senderNickname;
    private String senderAvatar;
    private Integer type;
    private Long articleId;
    private String articleTitle;
    private Long targetId;
    private String targetPreview;
    private String content;        // 动词短语，如 "赞了你的评论"
}
```

**Mapper**：`mapper/NotificationMapper.java` 继承 `BaseMapper<Notification>`，用 MyBatis-Plus 原生方法。

## 六、NotificationServiceImpl

```java
public void send(NotificationMessage msg) {
    if (msg == null || msg.getUserId() == null || msg.getUserId().equals(msg.getSenderId())) {
        return;  // 不给自己发
    }
    // 1. 写表
    Notification n = new Notification();
    BeanUtils... // 逐字段拷贝，见源码
    notificationMapper.insert(n);

    // 2. 回填雪花ID，发 MQ
    msg.setNotificationId(n.getNotificationId());
    rabbitTemplate.convertAndSend(
            RabbitMqConstants.TOPIC_EXCHANGE, "notification.push", msg);
}
```

其他方法：`getUnread/getAll/markAsRead(带 userId 校验)/markAllAsRead/getUnreadCount`。

## 七、MQ 消费者

```java
@RabbitListener(queues = QUEUE_NOTIFICATION)
public void handleNotification(NotificationMessage msg) {
    sseEmitterService.sendToUser(msg.getUserId(), msg);
}
```

## 八、SSE 推送服务

`SseEmitterService`：
- `ConcurrentHashMap<Long, SseEmitter>` 存在线用户连接
- `connect(userId)`：30 分钟超时；同一用户重连时 complete 旧连接覆盖
- `sendToUser(userId, msg)`：不在线直接跳过，离线推送靠"拉"

**为什么用 SSE 不用 WebSocket**：单向推送足够；基于 HTTP，复用鉴权/Nginx；浏览器 `EventSource` 原生自动重连；WebSocket 对通知这种场景过度设计。

## 九、Controller

`/api/notification` 下：
- `GET /stream` SSE 连接
- `GET /unread` 未读列表（最多 50）
- `GET /unread-count` 未读数（铃铛红点）
- `GET /list?page=1&size=20` 全部分页
- `POST /{id}/read` 单条已读
- `POST /read-all` 全部已读

## 十、业务埋点

每个业务方用 `NotificationMessage.builder()` 链式填字段，调 `notificationService.send(msg)`。

| 业务 | 文件 | type | articleId | articleTitle | targetId | targetPreview | content |
|------|------|------|-----------|--------------|----------|---------------|---------|
| 评论文章 | `ArticleCommentServiceImpl.create()` | `COMMENT_REPLY` | 文章ID | ✓ | 评论ID | 评论前100字 | `"评论了你的文章"` |
| 回复评论 | 同上 | `COMMENT_REPLY` | 文章ID | ✓ | 评论ID | 评论前100字 | `"回复了你的评论"` |
| 点赞文章 | `UserActionServiceImpl.like()` | `LIKE` | 文章ID | ✓ | 文章ID | null | `"赞了你的文章"` |
| 收藏文章 | `UserActionServiceImpl.collect()` | `COLLECT` | 文章ID | ✓ | 文章ID | null | `"收藏了你的文章"` |
| 关注用户 | `UserServiceImpl.follow()` | `FOLLOW` | null | null | 被关注者ID | null | `"关注了你"` |
| 评论点赞 | `ArticleCommentServiceImpl.action()` | `LIKE` | 文章ID | ✓ | 评论ID | 评论前100字 | `"赞了你的评论"` |

取消动作（unlike / uncollect / 取消点赞）**不发通知**。

### 10.1 调用模板

```java
notificationService.send(NotificationMessage.builder()
        .userId(接收者ID)
        .senderId(UserContext.getUserId())
        .senderNickname(sender.getNickName())
        .senderAvatar(sender.getAvatar())
        .type(NotificationTypeEnum.XXX.getCode())
        .articleId(文章ID或null)
        .articleTitle(文章标题或null)
        .targetId(目标ID)
        .targetPreview(预览或null)
        .content("动词短语")
        .build()
);
```

### 10.2 辅助：截断文本

通知预览限制 100 字。`ArticleCommentServiceImpl` 里有一个 private static 方法：

```java
private static String truncate(String s, int max) {
    if (s == null) return null;
    return s.length() <= max ? s : s.substring(0, max);
}
```

### 10.3 减少额外查询的小技巧

- 评论类埋点：文章标题通过 `articleMapper.selectById(articleId)` 额外查一次（此路径之前没查过）
- 点赞/收藏埋点：`article` 对象业务流程里已经查过，直接 `article.getTitle()` 复用
- 评论点赞：方法末尾已有 `comment = articleCommentMapper.selectById(commentId)`，发通知用 `comment.getContent()` 做预览、`comment.getArticleId()` 做跳转

## 十一、前端展示建议

通知卡片由 3 部分组成：

```
[头像]  {sender_nickname} {content}
        {article_title 或 target_preview}
        {相对时间，如 3 分钟前}
```

示例渲染：
- 评论通知：`张三 评论了你的文章` / 副标题 `《Spring 源码剖析》` / 详情 `"写得真好，收藏了"`
- 点赞文章：`李四 赞了你的文章` / 副标题 `《Spring 源码剖析》`
- 关注通知：`王五 关注了你` / 无副标题
- 评论点赞：`赵六 赞了你的评论` / 副标题 `你的评论："这段代码可以优化一下..."`

点击跳转：
- 有 `article_id` → 文章详情页；有 `target_id` 且 type 是评论类 → 锚定到评论
- 只有 `target_id`（关注通知）→ 跳 `target_id` 对应用户主页

## 十二、防重复推送（可选）

当前 listener 直推。若后续开并发消费或重试，用 Redis 幂等：

```java
String key = "notify:pushed:" + msg.getNotificationId();
if (Boolean.TRUE.equals(redisTemplate.opsForValue().setIfAbsent(key, "1", Duration.ofHours(1)))) {
    sseEmitterService.sendToUser(msg.getUserId(), msg);
}
```

## 十三、文件清单

| 状态 | 路径 | 说明 |
|------|------|------|
| ✅ | `entity/Notification.java` | 11 字段实体，含 4 个冗余快照字段 |
| ✅ | `dto/NotificationMessage.java` | `@Builder` 入参 + MQ 消息 |
| ✅ | `mapper/NotificationMapper.java` | |
| ✅ | `service/NotificationService.java` | `extends IService<Notification>` |
| ✅ | `service/impl/NotificationServiceImpl.java` | `send(NotificationMessage)` 单参签名 |
| ✅ | `service/impl/SseEmitterService.java` | 含超时/断线/重连覆盖 |
| ✅ | `listener/NotificationListener.java` | |
| ✅ | `controller/NotificationController.java` | 含 `unread-count` |
| ✅ | `enums/NotificationTypeEnum.java` | 5 个枚举值 |
| ✅ | `constants/RabbitMqConstants.java` | 加通知队列常量 |
| ✅ | `config/RabbitMqConfig.java` | 加队列绑定 |
| ✅ | `ArticleCommentServiceImpl.create()` | 评论 + 回复通知 |
| ✅ | `ArticleCommentServiceImpl.action()` | 评论点赞通知 |
| ✅ | `UserActionServiceImpl.like()/collect()` | 文章点赞/收藏通知 |
| ✅ | `UserServiceImpl.follow()` | 关注通知 |
| 📝 待建表 | `notification` | DDL 见第二节 |
| 📝 待升级 | 已存在的 notification 数据 | 需要 `ALTER TABLE` 加 4 个字段，旧数据的冗余字段会是 null |

## 十四、老数据迁移

如果 `notification` 表已经有数据，用 `ALTER TABLE` 加字段（默认 null，不影响老数据展示，只是没有昵称/头像/标题/预览）：

```sql
ALTER TABLE notification
    ADD COLUMN sender_nickname VARCHAR(64)  AFTER sender_id,
    ADD COLUMN sender_avatar   VARCHAR(255) AFTER sender_nickname,
    ADD COLUMN article_title   VARCHAR(200) AFTER article_id,
    ADD COLUMN target_preview  VARCHAR(200) AFTER target_id;
```

旧通知点开仍能跳转（id 还在），只是卡片上没有昵称/头像等快照信息。
