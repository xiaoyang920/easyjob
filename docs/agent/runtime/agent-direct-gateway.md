# 网关直达 Python Agent

2026-10-28。用户侧 AI 请求由网关直接路由到 Python，去掉 Blog 的 HTTP 转发环节。前端继续使用原有 `/api/agent/**` 地址。

## 请求路径与职责

```text
浏览器 → Gateway :8090 → Python Agent :8000
             │              │
             ↓              ├─ 执行、会话、任务结果、记忆、Checkpoint
        Auth :8081          └─ 必要的文章/草稿业务 RPC → Blog :20881
```

登录、注册、会话检查由 Auth 负责。网关校验外部访问 JWT，在线检查会话、限流，去除客户端提交的身份头，再签发面向 `easyjob-agent` 的内部身份。Python 使用网关公钥验证签名、发行者、用途、受众、方法、路径与时效，将用户 ID、会话 ID、账号版本放入请求上下文，退出请求时清理。

Python 不信任浏览器正文中的 userId，也不接受外部访问 JWT 直接调用其公开适配层。用户必须经过网关。会话/运行/记忆的归属校验仍在 Python 内执行；管理员接口留在 Java 权限边界内，没有对浏览器开放通用内部查询操作。

不需要经过 Java 才能启动 Agent；当 Agent 确实需要读取业务资料或保存草稿时，仍调用 Java 业务 RPC。Java 内部 Agent RPC 仅保留 ServiceQuery，供管理员、统计、用户偏好和就绪探针使用。旧用户侧 HTTP 转发入口及聊天 / 会话 / 记忆 / 流式 RPC 已于 2026-11-01 清理。这次没有拆开共享数据库，也没有取消 Java 的业务权限检查。

## 接口兼容

`app/public_api.py` 提供 25 个用户接口，覆盖聊天、流式回复、审批继续、取消、会话历史、问题导航、运行查询/恢复/重放、记忆管理、会话库、写作关联、反馈和交付指标。

保留原来的 camelCase 入参、JSON 响应外壳、字符串大整数 ID，以及 SSE 帧协议。会话/历史输出过滤内部字段。原始 Python 内部接口继续要求服务身份与用户委托，公开路由不会转发任意内部操作。

## 长连接和执行身份

公开 SSE 建立时再次检查会话，之后每 5 秒按会话去重、每批最多 50 个查询 Auth。单设备退出同时通过 Redis 撤销通知及时断开。认证依赖不可用时拒绝新订阅并关闭已失去校验保障的订阅；新订阅分别返回失效 401、依赖不可用 503。

Python 尚未订阅 RabbitMQ 账号变更事件，因此密码修改/封禁等由周期检查发现。检查周期不代表严格的全局关闭时限。

关闭订阅不自动取消持久化任务。取消仍走显式取消接口；新运行将会话信息绑定到 `agent_run`，敏感业务写入继续检查会话与业务授权。公开资料 RPC 使用服务身份，用户私有业务 RPC 则保留用户委托，避免把公开查询中的内部占位 ID 当成当前用户。

## 配置和上线顺序

1. 先部署 Python 新接口。配置 `GATEWAY_IDENTITY_PUBLIC_KEY_FILE`、`AUTH_SERVICE_BASE_URL`、`AUTH_SERVICE_CHECK_KEY`。只能挂载网关公钥，Python 不持有网关私钥。原 Blog 委托公钥与服务凭证继续保留。
2. 本地 `scripts/prepare-auth.py` 随 `prepare-local.py` 生成上述配置；已有运行配置需要补齐后重启 Python。网关公钥在启动时加载并缓存，轮换需协调接收方部署与重启。
3. 再发布网关：`agent-api` 路由放在 `/api/**` 通用 Blog 路由前，以 `lb://easyjob-agent` 使用 Consul 注册的 HTTP 端口。
4. Compose 已配置公钥只读挂载和 Auth 地址/凭证。容器配置校验不等于真实容器部署验证。

## 验证

- Python 62 项测试通过：公开 API 身份、参数/返回兼容、SSE 撤销、RPC 委托及执行仓储等。真实聊天联调还发现并修复了 `RunService.config` 缺少 settings 导入的问题，并新增执行身份恢复回归。
- Gateway 26 项测试通过并完成打包，包含真实 RSA 签名验证和路由顺序检查。
- `scripts/agent-direct-smoke.py`：27 项真实服务检查通过。创建临时账号，检查资源归属、历史/记忆/会话编辑、伪造身份拒绝与 SSE；隔离网关将 Java HTTP 目标设为不可达地址，Agent 查询仍返回成功，Java 路径返回 503。此检查不调用模型、不发邮件。
- 本次真实单设备退出使 Python SSE 在约 375 毫秒关闭，SQL 中执行仍为 running；重新连接返回 401。这是一次实测值，不是性能承诺。
- `scripts/agent-direct-chat-smoke.py` 已通过一次真实模型流式回复、运行会话绑定和历史落库验证；此次短回复耗时 2688 毫秒。结果保存在忽略目录 `temp/agent-direct-chat-report.json`；临时账号、会话和运行数据在检查后清理。
- Compose 配置校验通过；本地前端、Gateway、Auth、Blog、Agent 就绪检查均返回 200。没有执行生产或容器发布。

这些检查没有覆盖所有模型工具和管理操作，没有进行吞吐压测，不能据此宣称整体响应速度提升了固定比例。

本地 Python 修复通过 `scripts/restart-agent.ps1` 的空闲 admission guard 后重启。无定时触发器的 `EasyJob-Agent-Direct-20261028` 任务仅托管本地 Agent 生命周期；保持服务运行期间不要清理该任务，日志为 `logs/agent-direct-restart.log`。其他服务继续由原本地宿主维护。

## 旧中转清理（2026-11-01）

Java 已移除用户侧聊天、会话历史、记忆和交付指标转发；反馈控制器只保留 /api/admin/agent-feedback 管理接口。AgentRpc 不再暴露 ChatStream、ResumeStream、RunEvents、Recover 等方法，客户端连接池也不再维护流式回调租约。Python 的公开 HTTP/SSE 接口继续负责这些功能。

Python 调用 Java 的 BlogRpc 包含 ListDrafts、ReadDraft、SaveDraft、ReadPublic、Maintenance、DraftReceipt，全部是普通请求响应，没有流式调用。共享 IDL 已更新并重新生成 Python 代码，Java 需要重新构建；两侧协议应协调更新。
