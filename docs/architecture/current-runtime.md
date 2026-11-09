# 当前运行架构

更新：2026-11-01。

浏览器的 AI 请求由网关直接转给 Python。Python 负责模型调用、任务编排、上下文、记忆、会话历史和 SSE 输出；Java 负责业务数据、权限、文章索引及后台管理。

```text
前端 → Gateway → Python Agent → 模型 / 检索 / 工具
                    ↓ 需要业务数据或保存草稿
                 Java Blog RPC → Mapper → MySQL

文章发布 / 修改 → Java 索引 Outbox → MQ → 分块与 Embedding → Elasticsearch
管理员后台 → Java → Python ServiceQuery
```

## 服务职责

| 模块 | 职责 |
| --- | --- |
| `gateway` | 路由、认证准入、签名内部身份、限流和熔断 |
| `auth-service` | 登录、注册、令牌签发、会话管理和 JWKS |
| 根 Java 应用 | 文章、用户、好友消息、订单、权限、业务持久化和索引 |
| `python-agent` | LangGraph Agent 执行、模型调用、检索、上下文、长期记忆和流式交付 |
| `contracts` | Java / Python 共用的内部普通 RPC 协议 |

## Java 的 agent 包

保留的代码是 Python Agent 的业务配套，以及文章检索索引的写入链路：

- `component`：文章分块、ES 索引、索引 Outbox、投递和补偿。
- `config`：文章 Embedding 的并发和执行配置。
- `controller`：后台反馈管理、内部草稿接口、就绪探针。
- `rpc`：Python 查询 / 保存 Java 业务数据，Java 查询 Python 的后台数据。
- `security`：服务身份、执行身份和草稿保存许可。
- `service`：文章查询、草稿保存、文章 Embedding。

旧 Java 推理图、Worker、工具、聊天客户端、查询重写、重排、Java 检索入口、旧聊天缓存和专属 DTO 已移除。DeepSeek 聊天模型启动依赖和 Alibaba Graph 依赖也已移除；余额预警使用的 DeepSeek HTTP 客户端和文章索引使用的 Embedding 继续保留。

对应历史教程位于[旧 Java Agent 归档](../archive/java-agent/README.md)。这些示例不代表当前运行入口。

## 代码入口

- [Python 公开 Agent API](../../python-agent/app/public_api.py)
- [Python Agent 执行入口](../../python-agent/app/main.py)
- [Java Blog RPC](../../src/main/java/com/easyjob/agent/rpc/BlogRpcProvider.java)
- [文章索引消费者](../../src/main/java/com/easyjob/listener/ArticleVectorListener.java)
- [持久化规范](persistence-layer.md)
- [网关直达 Python 的说明](../agent/runtime/agent-direct-gateway.md)
