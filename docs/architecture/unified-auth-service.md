# 统一认证：运行方式与服务边界

2026-10-28。实现目标与阶段计划见 [实施计划](unified-auth-service-plan.md)。Agent 直连变更见 [网关直达 Python](../agent/runtime/agent-direct-gateway.md)。

## 当前链路

```text
浏览器 -> Gateway :8090
           登录/续签/注销 -> Auth :8081 -> Redis 会话 / MySQL 账号
           业务请求 -> 外部 RS256 验签 -> Auth 会话检查
                     -> Gateway 内部签名身份 -> /api/agent/** -> Python Agent :8000
                                            -> 其他业务接口 -> Blog :8080
Python Agent -> 文章/草稿等业务 RPC -> Blog :20881
Blog 管理接口 -> 服务身份 + 用户委托 -> Agent 内部 RPC
```

外部 Token 由 Auth 私钥签发，网关通过 `/api/auth/jwks` 获取公钥；声明包含发行者、受众、有效期、用户、会话 ID 与账号版本。

网关不读取会话 Redis 的内部存储格式，而是调用 `/internal/auth/session/check`。有效会话查询不做正向缓存；退出、封禁、密码/角色变化在下一次准入时生效。Auth、Redis 或状态查询不可用时拒绝受保护请求，返回 503；失效凭证返回 401。

网关清理浏览器伪造的身份头，再用另一把 RSA 私钥签发 15 秒的内部身份，绑定目标服务、方法和路径。Blog 和 Python 分别验证面向自己的内部身份，不再接受浏览器的访问 JWT 作为可信内部身份。资源归属、审批与具体业务权限仍由 Blog/Agent 判断。

内部和外部 JWT 均使用标准 `typ=JWT`，通过必需的 `token_use` 声明区分 access/gateway/delegation。该实现细节替代计划中自定义 JOSE typ 的写法，避免与 Spring 默认类型验证产生不一致。

## 代码位置

- `auth-service/`：独立 Spring Boot 服务。账号仓储、验证码、登录、续签、注销、密码、设备、管理员账号安全修改、JWKS、撤销 outbox。
- `auth-common/src/main/java/com/easyjob/security/`：共享身份协议、JWT 验证规则和路由分类。三个 Maven 工程以共同源码目录编译，不依赖另一个服务的实现包。
- `gateway/.../UnifiedIdentityFilter.java`：外部 Token 与在线会话准入、伪造身份头清理、内部身份签发。
- `src/main/java/com/easyjob/security/TrustedGatewayFilter.java`：Blog 内部身份验证、上下文安装与清理。
- `python-agent/app/security/gateway.py`、`public_api.py`：Python 验证网关身份并兼容网站原有的用户侧 Agent 接口。
- `ConnectionSessions`：WebSocket/SSE 撤销通知和周期性复查，断开订阅不会自动取消持久化的 Agent 任务。
- `AgentDelegation`、`AgentServiceAuth` 和 Python `app/security/delegation.py`：服务身份与用户委托验证。观察探针使用单独用途的短期凭证，不能启动用户任务。

`easyjob.auth.enabled=true` 时使用新架构，Blog 原登录 Controller 关闭。原认证类保留为显式旧模式兼容与回归基线，运行时不会在新认证失败后回退到旧模式。回退配置必须作为单独切换处理，并使旧会话失效。

## 数据与权限

第一版仍共享 `user_info`，因此没有完成数据库物理拆分。认证服务写密码、角色、状态、auth_version 和登录状态；Blog 的资料更新 SQL 只写资料字段，管理员角色/状态通过 Auth 的专用接口保存。两类修改有独立保存动作。

字段归属同时由应用代码与 MySQL 权限执行。Auth、Blog、Agent 使用三个独立运行账户：Auth 可以读取凭证、创建账号及更新安全字段；Blog 可以更新资料和业务数据，但不能读取密码、修改安全字段或访问认证审计/outbox；Agent 可以写执行/记忆等数据，业务文章只读，也不能读取密码。三个账户均没有 DDL、授权或迁移写入权限。注册仍由 Auth 在共享表内插入最小默认资料，这是保留的共享表依赖。

`scripts/auth_database_grants.py` 定义共同的列/表授权，`scripts/provision-auth-database.py` 为本地生成并保留自有账户，真实执行允许/禁止操作检查。账户凭证保存在忽略目录 `temp/auth-database-users.json`；维护/迁移仍用单独维护凭证。Python 启动脚本只给服务进程设置 `EASYJOB_AGENT_RUNTIME=true` 以选用 Agent 账户，不影响随后执行的迁移命令。新增迁移创建表后应在应用启动前重新运行授权脚本。

新增迁移：

- `029_auth_service.sql`：`auth_audit`、`auth_outbox`，以及 `agent_run.auth_sid/auth_version`。
- `030_auth_audit_reason.sql`：保存管理员修改原因。

会话使用新命名空间 `auth:v2:*`。切换后旧登录需要重新登录。Redis 中保存续签凭证摘要，浏览器保存 HttpOnly、SameSite=Strict Cookie。生产 HTTPS 配置 Secure；本地 HTTP 不启用 Secure。

默认访问 Token 30 分钟；会话闲置 7 天、绝对期限 30 天。续签仍沿用固定高熵凭证，尚未实现刷新凭证轮换与重用检测。

账号安全变更和撤销 outbox 在一个 MySQL 事务中提交，RabbitMQ 发布确认后标记完成。每个 Blog 实例有自己的撤销队列。单设备退出的 Redis 删除和通知没有跨库原子性，因此另用周期状态检查补偿。

Blog 活跃连接每 30 秒按批检查会话，失败则关闭；撤销事件到达时尽快关闭。Python SSE 订阅建立时检查一次，之后每 5 秒按会话去重、每批至多 50 个检查，并监听 Redis 单设备退出事件。Python 暂未消费 RabbitMQ 账号变更事件，密码/封禁等变化由周期检查发现。大量连接或慢依赖会增加批次耗时，这些周期不是严格的全局撤销 SLA。业务消息/写入仍需资源权限判断。

Agent 的新执行把发起会话关联到 `agent_run`。审批继续与故障恢复通过认证入口重新绑定当前会话；保存草稿前 Blog 再查询会话状态，并保留执行 fencing、审批 permit、草稿归属和版本锁。授权记录是服务器状态，不是把过期 JWT 当成永久授权存入 Checkpoint。

## 本地运行

1. 应用新增迁移（启动脚本不隐式迁移）。已有环境可只通过 `app.migrate.apply_product_features` 应用 029、030；完整新环境使用既有迁移入口。
2. 执行 `python-agent/.venv/Scripts/python.exe scripts/prepare-local.py`。它生成忽略目录内的配置与持久化密钥，不输出凭证。
3. 确认 MySQL 已就绪，执行 `python-agent/.venv/Scripts/python.exe scripts/provision-auth-database.py`。脚本只管理忽略清单中归属本项目的三个账户，并检查列/表权限。再次执行 `prepare-local.py` 会保留这些运行账户。
4. 分别构建根 Java、`auth-service/pom.xml`、`gateway/pom.xml`。运行中的 JAR 不直接覆盖，使用隔离构建目录，再交给重启脚本。
5. 执行 `scripts/start-local.ps1`，按依赖、Auth、Blog、Agent、Gateway、前端的顺序启动。已有服务使用 `scripts/restart-unified-auth.ps1`，它在确认 Agent 空闲并持有 admission guard 后切换已验证的构建。

配置文件：`temp/application-runtime.yml`、`temp/auth-runtime.yml`、`temp/gateway-runtime.yml`。密钥位于忽略目录 `temp/auth-keys/`。这些文件不提交仓库。

健康检查：Auth `:8081/actuator/health`；Blog `:8080/actuator/health`；Agent `:8000/health/ready`；网关 `:8090/actuator/health`。跨服务只读探针使用 `scripts/agent-rpc-ready.py`，需要内部服务凭证。

Windows 上这次开发服务由无定时触发器的隐藏任务托管。相关登记作为后台进程宿主，保留至停服后再清理，避免进程意外退出。启动宿主记录在 `temp/unified-auth-service-host-task.txt`，本次切换宿主记录在 `temp/unified-auth-database-restart-task.txt`；它们只用于维持进程，不是周期任务。电脑关机或注销期间服务不会持续运行。

Auth 使用 Consul TTL 心跳，避免 Docker 内的 Consul 无法通过自己的 127.0.0.1 检查宿主机服务。实例 ID 每次启动唯一，异常实例超时清理。

## Auth 签名密钥轮换

```powershell
.\python-agent\.venv\Scripts\python.exe scripts\rotate-auth-key.py prepare
# 确认 JWKS 已包含新 kid，等待公钥缓存刷新窗口
.\python-agent\.venv\Scripts\python.exe scripts\rotate-auth-key.py activate
# 使用 restart-auth.ps1 重启 Auth，开始签发新 kid
```

准备阶段发布新公钥，激活阶段更换磁盘签名密钥；Auth 重启后采用新私钥。旧公钥至少保留 30 分钟加时钟偏差。最多加载 8 个附加公钥，轮换前清理已经超过保留窗口的历史公钥。脚本不会自动删除历史目录或旧公钥。

Gateway 和 Blog 内部签名密钥的轮换需要接收方先部署兼容的验证公钥并协调切换，第一版没有自动化整个内部密钥轮换流程。

## 容器配置

Compose 增加 Auth 服务，内部端口不对公网发布；网关增加 Auth 路由。各服务分别挂载自己需要的私钥/公钥，网关不持有 Auth 私钥。

新环境 `scripts/deploy.py init-env` 生成 `AUTH_SERVICE_KEY`、三个独立数据库密码及 `deploy/secrets` 密钥。已有环境需要补充 `AUTH_DB_PASSWORD`、`BLOG_DB_PASSWORD`、`AGENT_DB_PASSWORD`（各至少 32 字符）和认证服务配置，再执行 `scripts/generate-auth-keys.py deploy/secrets`；不要覆盖已有部署密钥。

容器按 `migrate → database-permissions → Auth/Blog/Agent` 启动。一次性授权容器通过专用 MySQL Unix socket 使用维护权限，随后核对运行账户的允许/禁止操作；业务容器只接收自身数据库凭证，不持有维护密码。授权与本地共用同一脚本。备份暂停写入者时也包含 Auth，恢复后重新应用运行账户授权。密钥目录不进入 Docker 构建上下文，Auth 的环境变量配置模板则保留在构建上下文。

Linux 下私钥文件必须可被容器 UID 10001 读取且不对其他用户开放。配置检查不替代文件权限与真实容器启动验证。生产需 HTTPS，跨主机内部通信需 TLS；mTLS 尚未启用。

## 验证与边界

- Auth 的协议与会话测试验证签名/用途/受众/方法路径、过期、不同密钥和续签竞态。
- 网关测试验证匿名/保护接口、伪造身份头、无效可选凭证、续签 Cookie、下游异常边界。
- Python 委托测试与既有 RPC/执行仓储测试一起运行。
- `scripts/unified-auth-smoke.py` 使用临时账号真实检查网关、Auth、Blog、Agent、设备撤销、封禁和 WebSocket。通过 Redis 仅注入这些临时账号的验证码以避免发测试邮件；所有凭证在内存，结束清理账号和会话。
- `scripts/unified-auth-resilience-smoke.py` 在隔离端口启动真实 Auth/Gateway，用故障代理中断它们的 Auth、JWKS、Redis 连接，并实际重启 Auth 完成密钥轮换。测试不停止主站服务；结果在 `temp/unified-auth-resilience-report.json`。
- `scripts/unified-auth-cluster-smoke.py` 启动不注册服务发现、不执行余额轮询的第二个 Blog JVM。改密码产生真实 SQL outbox/RabbitMQ 事件，验证两个实例上的会话连接同时关闭；结果在 `temp/unified-auth-cluster-report.json`。
- 真实测试记录在 `temp/unified-auth-smoke-report.json`，只包含检查结果与耗时，不含 Token、密码或服务密钥。性能测的是整个请求链路，不能等同于纯认证开销，也没有据此宣称比旧架构更快。

尚未实现的后续学习内容：独立账号数据库、OAuth2 授权码/PKCE、OIDC 标准发现与 SSO、mTLS、刷新凭证轮换、内部密钥自动轮换、分布式账号/资料创建补偿。

## 本次验证结果

2026-10-27 完成：Auth 9 项、Gateway 24 项、Blog 41 项、Python 44 项、前端认证 13 项测试，共 131 项通过；前端 TypeScript 检查通过，Compose 配置校验通过。没有在此次本地验证中完整构建并部署整套容器。

切换到独立数据库账户并重启后，54 项真实接口检查通过，包含注销/设备撤销/封禁/改与重置密码、验证码登录、旧 Token 拒绝、网关到 Agent 身份传递、已有 WebSocket 与通知 SSE 的关闭，以及资料修改、草稿/私信/联系人/通知列表。伪造资料更新不能改变凭证与角色。数据库连接表确认三个服务使用各自账户。100 次认证请求整体 p50 为 37.66 ms，p95 为 46.79 ms；这是本机链路耗时，未据此宣称比旧架构更快。没有模型调用或测试邮件。临时账号清理后数量为 0，重启 admission lease 已释放。

额外 19 项真实隔离检查通过：认证服务依赖故障返回 503、匿名文章仍可读、每个业务请求只有一次网关会话查询、JWKS 故障时已缓存公钥仍可用而新公钥查询失败返回 503、签名密钥预发布/激活并重启 Auth 后新旧 Token 均可用，以及 Auth/Gateway 两侧 Redis 连接中断后的拒绝与恢复。

双 Blog 实例的 6 项真实检查通过，改密码产生的 RabbitMQ 撤销事件在约 2.39 秒内关闭两个实例上的连接，outbox 发布确认已写回，失效会话不能发起新请求。这是本机单次观测，不是全局延迟保证。测试实例没有保留在服务发现中。合计 79 项真实检查通过；完整容器部署仍需目标环境验证。

Auth、Blog、Agent、Gateway、前端均通过健康检查；Java→Agent 探针连续两次成功。原有 DeepSeek 余额预警仍正常，最近成功读到 4.79 元，失败次数 0。
