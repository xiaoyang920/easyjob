# RPC metadata 验证记录

更新日期：2026-11-01。当前协议已清理旧聊天中转；本记录对应清理后的普通 RPC。此前流式 RPC 验证仅属于旧协议历史，不能用于说明当前业务还有流式 RPC。

## 当前业务边界

- 浏览器聊天、审批继续、运行事件和恢复输出：Gateway → Python HTTP/SSE。
- Java → Python：AgentRpc.ServiceQuery，供后台统计、管理、用户偏好和就绪检查使用。
- Python → Java：BlogRpc 的 ListDrafts、ReadDraft、SaveDraft、ReadPublic、Maintenance、DraftReceipt，均为普通请求响应。
- 标准 W3C traceparent / tracestate 通过 HTTP/2 metadata 传播；Identity 保持原有六个身份字段，不存放追踪上下文。

## 已完成检查

1. 根 Java 应用重新生成协议、编译通过，34 项指定测试通过，0 失败、0 跳过。包含通过真实 TCP 运行的 Java Dubbo Triple ↔ Python gRPC 互调，覆盖 ServiceQuery、大整数、业务冲突、错误服务身份、服务发现引用及草稿读取 / 保存权限边界。
2. Gateway 的 DirectAgentTests 两项通过，确认 /api/agent/** 先于通用 Java 路由匹配，目标为 easyjob-agent，网关签名身份面向 Python。
3. Python 53 项测试通过，覆盖公开 API、记忆 / 交付指标校验、内部 RPC 鉴权、观察凭证限制、并发上下文、连接池、就绪探针及现有追踪回归。
4. 原 RPC 聊天取消场景已迁移到真实本地 HTTP/SSE：同时打开两个流，取消一个运行，确认另一个仍运行，概览请求可响应，取消流和另一流都能正常结束。
5. 新增 Java 路由边界检查，扫描实际 Controller，确认 Java 不再声明 /api/agent 用户入口；Java / Python 协议描述均确认没有流式方法，AgentRpc 只有 ServiceQuery。
6. 共享 IDL 与 Python 生成代码一致性检查通过。

## 完整追踪示例的隔离验证

TraceSupport、RpcMetadataFilter、精简后的 TracingAgentRpc 和独立 Java 夹具编译通过。测试使用本地临时端口，运行独立 Java / Python 测试服务，通过真实 TCP / HTTP/2 验证：

- Dubbo SPI 自动加载 Filter。
- Java CLIENT → Python SERVER 与 Python CLIENT → Java SERVER 的 Trace ID 和直接父 Span ID。
- 八路并发上下文隔离，缺失 / 非法追踪头建立新根。
- Reply.error 标记错误，原有 metadata 保留。
- 其它接口使用动态服务名 / 方法名；Java CompletionStage 等待真实完成且不泄漏当前上下文。

第八章内嵌示例与完整示例文件一致，Python 代码片段语法检查及对真实模块的接入替换检查通过；Java 示例使用明确类型。

## 验证范围

这些检查使用隔离测试服务与替身业务依赖，没有调用真实模型、订单、邮件或生产数据库。此次未重启业务服务，也没有声称已在运行中的完整业务链路验收 Jaeger。第八章业务追踪代码仍按手敲进度接入，不能把示例验证当成业务 Filter 已注册。

共享协议已收敛，两侧部署时应协调更新。Java 使用新的构建输出目录验证，避免旧生成源码和已删除 Controller 的旧 class 混入结果；后续构建也应使用干净输出目录。
