# AI 聊天功能接口文档

## 1. AI 聊天接口

### 1.1 发送消息并获取 AI 回复

**接口地址**: `POST /ai/chat`

**请求头**:
```
Authorization: Bearer {token}
Content-Type: application/json
```

**请求参数**:
```json
{
  "message": "帮我优化这个标题：Spring Boot 入门教程"
}
```

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| message | String | 是 | 用户发送的消息内容 |

**响应示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "reply": "我帮你优化了这个标题，提供几个更吸引人的版本：\n\n1. 「从零开始掌握 Spring Boot：完整入门指南」\n   - 强调从零开始，降低门槛\n   - 突出"完整"和"指南"，增加价值感\n\n2. 「Spring Boot 实战入门：30 分钟搭建你的第一个应用」\n   - 加入时间承诺，更具体\n   - "实战"更有吸引力\n\n3. 「新手必看！Spring Boot 核心概念与快速上手」\n   - 明确目标读者\n   - 突出核心内容\n\n建议选择第 2 个，因为它既有时间承诺又强调实战，更容易吸引读者点击。"
  }
}
```

**响应字段说明**:
| 字段名 | 类型 | 说明 |
|--------|------|------|
| code | Integer | 状态码，200 表示成功 |
| message | String | 响应消息 |
| data.reply | String | AI 的回复内容 |

**错误响应**:
```json
{
  "code": 401,
  "message": "未登录或 token 已过期",
  "data": null
}
```

```json
{
  "code": 400,
  "message": "消息内容不能为空",
  "data": null
}
```

```json
{
  "code": 500,
  "message": "AI 服务异常，请稍后重试",
  "data": null
}
```

---

## 2. 前端实现说明

### 2.1 路由配置
- 路由路径: `/ai-chat`
- 组件: `AiChat.vue`
- 需要登录: 是

### 2.2 页面功能
1. **欢迎界面**: 首次进入显示欢迎信息和快捷问题
2. **消息列表**: 显示用户和 AI 的对话历史
3. **输入框**: 支持多行输入，Enter 发送，Shift+Enter 换行
4. **快捷问题**: 点击快捷问题快速发送

### 2.3 入口位置
1. **导航栏**: 右侧导航菜单中的 "AI" 按钮
2. **功能卡片**: 首页右侧功能卡片区域的 "AI 助手" 卡片

---

## 3. 后端实现建议

### 3.1 技术栈
- Spring AI + DeepSeek Chat Model
- 已配置的 ChatClient Bean

### 3.2 实现步骤

#### 3.2.1 创建 Service 接口
```java
package com.easyjob.service;

public interface AiChatService {
    String chat(String message);
}
```

#### 3.2.2 创建 Service 实现类
```java
package com.easyjob.service.impl;

import com.easyjob.service.AiChatService;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

@Service
public class AiChatServiceImpl implements AiChatService {
    
    private final ChatClient chatClient;
    
    public AiChatServiceImpl(ChatClient chatClient) {
        this.chatClient = chatClient;
    }
    
    @Override
    public String chat(String message) {
        return chatClient.prompt()
                .user(message)
                .call()
                .content();
    }
}
```

#### 3.2.3 创建 Controller
```java
package com.easyjob.controller;

import com.easyjob.service.AiChatService;
import com.easyjob.vo.ResponseVO;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/ai")
public class AiController {
    
    private final AiChatService aiChatService;
    
    public AiController(AiChatService aiChatService) {
        this.aiChatService = aiChatService;
    }
    
    @PostMapping("/chat")
    public ResponseVO<Map<String, String>> chat(@RequestBody Map<String, String> request) {
        String message = request.get("message");
        
        if (message == null || message.trim().isEmpty()) {
            return ResponseVO.error(400, "消息内容不能为空");
        }
        
        try {
            String reply = aiChatService.chat(message);
            return ResponseVO.success(Map.of("reply", reply));
        } catch (Exception e) {
            return ResponseVO.error(500, "AI 服务异常，请稍后重试");
        }
    }
}
```

### 3.3 配置说明
确保 `application.yml` 中已配置 DeepSeek API Key：
```yaml
spring:
  ai:
    deepseek:
      api-key: your-api-key-here
      chat:
        options:
          model: deepseek-chat
          temperature: 0.7
          max-tokens: 2000
```

**系统提示词**（已在 `ChatClientConfiguration` 中配置）：
```
你是 EasyJob 技术博客平台的 AI 写作助手。你的职责是：
1. 帮助用户优化文章标题和内容，提升文章质量
2. 提供技术写作建议，改善文章结构和表达
3. 帮助用户润色文字，使表达更专业、清晰
4. 提供写作灵感和选题建议
5. 解答技术问题，帮助用户创作更好的技术文章
6. 介绍平台功能使用方法

请用专业、友好的语言回答，注重实用性。
```

---

## 4. 注意事项

1. **权限控制**: 接口需要验证用户登录状态
2. **错误处理**: 需要捕获 AI 服务异常并返回友好提示
3. **性能优化**: 
   - 考虑添加请求超时控制
   - 可以添加请求频率限制防止滥用
4. **未来扩展**: 
   - 可以添加对话历史记录功能
   - 可以实现流式响应提升用户体验
   - 可以添加上下文管理实现多轮对话

---

## 5. 测试建议

### 5.1 功能测试
- 测试正常消息发送和接收
- 测试空消息的错误处理
- 测试未登录状态的拦截
- 测试 AI 服务异常的处理

### 5.2 性能测试
- 测试响应时间
- 测试并发请求处理能力

### 5.3 用户体验测试
- 测试快捷问题功能
- 测试消息列表滚动
- 测试输入框交互（Enter/Shift+Enter）
- 测试移动端适配
