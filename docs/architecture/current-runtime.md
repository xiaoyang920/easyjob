# 当前运行架构

更新：2026-11-01。

浏览器的 AI 请求由网关直接转给 Python。Python 负责模型调用、任务编排、上下文、记忆、会话历史和 SSE 输出。Blog 负责业务数据、权限及后台管理，索引由独立服务写入。

```text
前端 → Gateway → Python Agent → 模型 / 检索 / 工具
                    ↓ 需要业务数据或保存草稿
                 Java Blog RPC → Mapper → MySQL

文章发布 / 修改 / 下架 → Blog 索引 Outbox → RabbitMQ → Search Index → Elasticsearch
                                                    ↕ 内部 HTTP 取数和回执
                                                    Blog
管理员后台 → Java → Python ServiceQuery
```

聊天由 Main 按信息缺口调用工具。用户明确要求核对说法时，Main 读取对应原文或执行记录并逐条给出判断和依据。普通聊天和带资料的回答在生成正文时推送增量，交付阶段检查引用编号、站内来源版本和可识别的执行状态，记录最终正文及实际使用的引用。草稿审批和编辑器替换建议仍保留各自的内容核验。

## 服务职责

| 模块 | 职责 |
| --- | --- |
| `gateway` | 路由、认证准入、签名内部身份、限流和熔断 |
| `auth-service` | 登录、注册、令牌签发、会话管理和 JWKS |
| `blog-service` | 文章、用户、好友消息、订单、权限、业务持久化、搜索查询和索引 Outbox |
| `search-index-service` | 消费文章索引任务、分块与 Embedding、写入 Elasticsearch、向 Blog 确认完成 |
| `python-agent` | LangGraph Agent 执行、模型调用、检索、上下文、长期记忆和流式交付 |
| `contracts` | Java / Python 共用的内部普通 RPC 协议 |

## Java 的 agent 包

保留的代码是 Python Agent 的业务配套，以及文章检索索引的写入链路：

- `component`：文章索引 Outbox、投递、补偿和批量重建排队。
- `controller`：后台反馈管理、内部草稿接口、就绪探针。
- `rpc`：Python 查询 / 保存 Java 业务数据，Java 查询 Python 的后台数据。
- `security`：服务身份、执行身份和草稿保存许可。
- `service`：文章查询、草稿保存。

旧 Java Agent 教程包含推理图、Worker、工具和聊天客户端等历史实现。Blog 继续运行余额预警的 DeepSeek HTTP 客户端。文章索引服务独立运行 Embedding。

对应历史教程位于[旧 Java Agent 归档](../archive/java-agent/README.md)。这些示例不代表当前运行入口。

## 代码入口

启用 Nacos 后，Blog 注册 HTTP 实例，搜索索引服务通过 `easyjob-blog` 查找取数和完成回执接口。可选的部署、验收和切回直连步骤见 [本地启动文档](../operations/local-startup.md#可选的-nacos-服务发现)。

- [Python 公开 Agent API](../../services/python-agent/app/public_api.py)
- [Python Agent 执行入口](../../services/python-agent/app/main.py)
- [Java Blog RPC](../../services/blog-service/src/main/java/com/easyjob/agent/rpc/BlogRpcProvider.java)
- [文章索引消费者](../../services/search-index-service/src/main/java/com/easyjob/listener/ArticleVectorListener.java)
- [Blog 内部取数和完成回执](../../services/blog-service/src/main/java/com/easyjob/controller/InternalSearchIndexController.java)
- [持久化规范](persistence-layer.md)
- [网关直达 Python 的说明](../agent/runtime/agent-direct-gateway.md)
