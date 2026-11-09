# 文章聊天室 WebSocket 接口文档

## 一、连接建立

| 项目 | 内容 |
|------|------|
| **WebSocket 路径** | `ws://域名/ws/article?token=xxx` |
| **连接参数** | `token`: JWT 令牌（必填） |
| **说明** | 用户进入文章详情页时建立连接，离开页面时断开 |

---

## 二、前端发送事件

### 2.1 进入文章（join_article）

**时机**：WebSocket 连接成功后立即发送

**格式**：
```json
{
  "type": "join_article",
  "articleId": "123"
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | String | 是 | 固定值：`join_article` |
| articleId | String | 是 | 文章ID |

**后端处理**：
1. 解析 token 获取用户信息
2. 将用户添加到该文章的在线用户列表
3. 向该文章所有在线用户广播 `article_users_update` 事件

---

### 2.2 离开文章（leave_article）

**时机**：用户离开页面或关闭连接前发送

**格式**：
```json
{
  "type": "leave_article",
  "articleId": "123"
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | String | 是 | 固定值：`leave_article` |
| articleId | String | 是 | 文章ID |

**后端处理**：
1. 从该文章的在线用户列表中移除用户
2. 向该文章剩余在线用户广播 `article_users_update` 事件

---

### 2.3 发送聊天消息（article_chat_message）

**时机**：用户在聊天室发送消息时

**格式**：
```json
{
  "type": "article_chat_message",
  "articleId": "123",
  "content": "这篇文章写得不错"
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | String | 是 | 固定值：`article_chat_message` |
| articleId | String | 是 | 文章ID |
| content | String | 是 | 消息内容（最大500字符） |

**后端处理**：
1. 校验消息内容（非空、长度限制）
2. 补充发送者信息（从 token 解析）
3. 向该文章所有在线用户广播消息（包括发送者）

---

## 三、后端推送事件

### 3.1 在线用户列表更新（article_users_update）

**触发时机**：
- 有用户进入文章
- 有用户离开文章
- 用户连接断开

**格式**：
```json
{
  "type": "article_users_update",
  "articleId": "123",
  "users": [
    {
      "userId": "1",
      "nickName": "用户A",
      "avatar": "/uploads/avatar/xxx.jpg"
    },
    {
      "userId": "2",
      "nickName": "用户B",
      "avatar": "/uploads/avatar/yyy.jpg"
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| type | String | 固定值：`article_users_update` |
| articleId | String | 文章ID |
| users | Array | 当前在线用户列表 |
| users[].userId | String | 用户ID |
| users[].nickName | String | 用户昵称 |
| users[].avatar | String | 用户头像URL |

**说明**：
- 广播给该文章所有在线用户
- 前端接收后直接替换整个在线用户列表

---

### 3.2 聊天消息广播（article_chat_message）

**触发时机**：用户发送聊天消息后

**格式**：
```json
{
  "type": "article_chat_message",
  "articleId": "123",
  "userId": "1",
  "nickName": "用户A",
  "avatar": "/uploads/avatar/xxx.jpg",
  "content": "这篇文章写得不错",
  "timestamp": "2026-01-27T12:00:00"
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| type | String | 固定值：`article_chat_message` |
| articleId | String | 文章ID |
| userId | String | 发送者用户ID |
| nickName | String | 发送者昵称 |
| avatar | String | 发送者头像URL |
| content | String | 消息内容 |
| timestamp | String | 消息时间（ISO 8601格式） |

**说明**：
- 广播给该文章所有在线用户（包括发送者自己）
- 前端会过滤掉自己发送的重复消息（通过 userId 判断）

---

## 四、数据结构设计

### 4.1 内存数据结构

**文章在线用户管理**：
```
Map<String articleId, Set<WebSocketSession>> articleSessions
```
- Key：文章ID
- Value：观看该文章的所有 WebSocketSession 集合

**Session 用户信息映射**：
```
Map<WebSocketSession, ArticleUserInfo> sessionUsers
```
- Key：WebSocket 会话
- Value：用户信息对象

### 4.2 ArticleUserInfo 结构

| 字段 | 类型 | 说明 |
|------|------|------|
| userId | String | 用户ID |
| nickName | String | 用户昵称 |
| avatar | String | 用户头像URL |
| currentArticleId | String | 当前所在文章ID |

---

## 五、错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| Token 无效 | 拒绝连接，返回 401 |
| articleId 不存在 | 接受连接但返回空用户列表 |
| 消息内容为空 | 忽略该消息，不广播 |
| 消息内容超长 | 截断至500字符后发送 |

---

## 六、Nginx 配置

在 Nginx 中添加 `/ws/article` 的 WebSocket 代理配置：

```nginx
location /ws/article {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400;
}
```

---

## 七、业务流程图

### 7.1 用户进入文章

```
用户打开文章详情页
       ↓
建立 WebSocket 连接（携带 token）
       ↓
后端解析 token，获取用户信息
       ↓
前端发送 join_article 事件
       ↓
后端将用户添加到 articleSessions
       ↓
后端广播 article_users_update 给该文章所有用户
       ↓
前端更新在线用户列表
```

### 7.2 发送聊天消息

```
用户在聊天室输入消息
       ↓
前端发送 article_chat_message 事件
       ↓
后端补充发送者信息（userId、nickName、avatar、timestamp）
       ↓
后端广播完整消息给该文章所有用户
       ↓
前端显示消息（自己发送的消息不重复添加）
```

### 7.3 用户离开文章

```
用户关闭页面 / 切换路由
       ↓
前端发送 leave_article 事件
       ↓
后端从 articleSessions 移除该用户
       ↓
后端广播 article_users_update 给该文章剩余用户
       ↓
前端更新在线用户列表
```
