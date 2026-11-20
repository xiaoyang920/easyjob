# 本机开发服务

前端：http://127.0.0.1:3000；Java：http://127.0.0.1:8080；Python Agent：http://127.0.0.1:8000/health。

依赖：现有 MySQL 3306、Docker Redis Stack 缓存 6379/DB3、专用 Checkpointer Redis 6380/DB0、Elasticsearch 9.2.4（IK）9200、RabbitMQ 5672。

Checkpoint 容器为 `easyjob-checkpoint-redis`，数据卷为 `easyjob-checkpoint-data`，启用 AOF，端口仅映射到本机。镜像固定到已安装镜像的摘要。旧版 Windows Redis 缺少 Checkpointer 所需的 RedisJSON / RediSearch，当前使用 Docker 中的服务。若 6379 已监听，启动脚本会复用并校验该服务。否则由 `easyjob-cache-redis` 提供普通缓存，只映射本机 6379，数据保存在 `easyjob-cache-data`。

## 启动

在仓库根目录执行：

```powershell
.\services\python-agent\.venv\Scripts\python.exe scripts\prepare-local.py
.\scripts\start-local.ps1
```

启动器默认启动 Excel 导出服务。已有数据库缺少导出任务表时使用 `启动项目.cmd -Migrate`，只调试其他功能时可用 `启动项目.cmd -SkipExcel`。详见 [Excel 导出启动和验收](excel-service.md)。

已有环境升级空间装扮时，先停止 Blog、Python Agent 和 Excel，再运行 `启动项目.cmd -Migrate` 应用迁移 034 至 040。启动器会刷新本机 Blog 账号所需的空间装扮权限。登录后可在「硬币商城 → 空间皮肤」购买套装或单件，也可直接从「个人空间 → 空间装扮」试穿在售单件和保存已拥有的搭配。已购套装自动解锁其中的单件。日间、夜间、跟随系统由页头按钮切换并在当前浏览器保存。

空间头图免费上传。默认按 16:9 取景，可改为 21:9、3:2 或 4:3，并调整横向和纵向位置。上传保留源图比例，最长边限制为 2560 像素。待审图片仅本人和有审核权限的人员可以预览，访客继续看到之前的头图。在「管理后台 → 空间头图审核」通过后，访客可看到新头图和保存的取景。旧头图可通过重新上传原图提升清晰度。

管理员可在「管理后台 → 装扮商品管理」制作和预览组件，将其单独上架或加入套装，并在商品列表修改名称、价格、顺序和上下架状态。排序值越小越靠前。下架后已有用户可继续使用。组件保存在 `space_dress_part`，套装和单件商品共同保存在 `space_skin`，购买记录继续使用 `user_space_skin`。新的组件使用后台提供的基础样式，可以配置颜色、描边或上传图片，图片由服务端转为 PNG。

「组件列表」支持修改已保存的基础样式、颜色、描边和图片。修改会应用到引用该组件的商品和用户空间。未被商品与用户搭配引用的组件可以删除。

`dress_json` 保存头像框、卡片、图标和横幅纹样的组件编号。空值使用经典样式，迁移 039 为已有套装补齐组件目录，并为这 12 个部件提供可在后台调整的初始单件商品。

| 字段 | 支持的值 |
| --- | --- |
| `cardStyle` | `classic`、`binding`（书脊）、`floating`（柔影）、`postcard`（明信片） |
| `avatarFrame` | `classic`、`wreath`（双环）、`orbit`（光环）、`stamp`（邮票） |
| `iconPack` | `classic`、`library`（书房）、`celestial`（星月）、`postal`（邮局） |
| `bannerPattern` | `classic`、`arches`（弧纹）、`stars`（星点）、`postmark`（邮戳） |

启动器默认在 Blog 就绪后启动索引服务，健康检查地址为 `http://127.0.0.1:8084/actuator/health`。升级已有本地进程时，先停止旧版 Blog，再重新运行启动器，以免旧版和新版同时消费索引队列。启动器将服务密钥和连接配置写入 Git 忽略的 `temp/search-index-blog.yml` 与 `temp/search-index-runtime.yml`，本地日志在 `logs/search-index.*.log`。

部署已有 Compose 环境时，在原 `deploy/.env` 中加入两个独立的随机值 `INDEX_DB_PASSWORD` 和 `SEARCH_INDEX_SERVICE_KEY`，每个至少 32 字节，再用原 Compose 项目重新构建并启动。新环境执行 `python scripts/deploy.py init-env` 时会生成这两项。索引服务的 MySQL 账号只用于取得逐篇索引锁，文章、标签和 Outbox 由 Blog 的内部接口提供。

在本机启动后，可发布一篇测试文章，再修改标题并下架。发布和修改后通过站内搜索检查最新标题，下架后应搜不到。索引服务成功消费时会记录文章 ID，Blog 的 `article_index_outbox` 对应任务会变为 `completed`。GitHub Actions 使用独立数据库和本地 Embedding 模拟服务验收这条链路。

脚本沿用本机已安装的 Java、ES、RabbitMQ、Node；路径可以通过脚本参数覆盖。所有新进程在后台启动，日志保存到 `logs/`。ES 新启动时使用 1GB 堆。RabbitMQ 使用用户进程，无须修改 Windows 服务权限。Java 绑定回环地址，以避开系统网卡对 8080 的占用。

运行前需要已有 `services/python-agent/.env` 中的 MySQL/API 配置；新增密钥与 Redis 覆盖配置写入被 Git 忽略的 `services/python-agent/.env.runtime.local` 和 `temp/application-runtime.yml`。旧 `.env` 已被仓库跟踪，脚本不修改它。脚本不会自动执行数据库迁移或全文索引重建。

若修改 Java 代码，先停止对应的项目 Java 进程再执行 `scripts/start-local.ps1 -Build`。重建旧文章的 HTML 文本块时，停止 Blog 后用 `scripts/start-local.ps1 -Reindex`。Blog 日志中的“HTML块重建排队完成”表示已经写入 Outbox。索引服务随后调用 Embedding API，写入成功后将对应任务标为 `completed`。

Blog 需要重建时，启动器会在 `services/blog-service/` 执行 `clean package`，使用专用构建目录 `services/blog-service/target/local-launcher`，再复制生成的 JAR。删除 RPC 协议消息或 Java 源文件后，普通增量 `package` 可能保留旧的生成代码和类文件，导致编译错误或把已删除的类打入 JAR；清理专用构建目录可避免这类残留。

## 可选的 Nacos 服务发现

Blog 就绪后，以 `easyjob-blog` 注册自身的 HTTP 地址。它每 5 秒续约一次，正常关闭时注销。搜索索引服务按服务名选择健康且已启用的实例，实例列表缓存 3 秒。请求仍使用原有的 `SEARCH_INDEX_SERVICE_KEY`。网关和 Agent 的现有发现链路继续使用 Consul。

### Windows 本地启动

在项目根目录的 PowerShell 中启动单独的 Nacos。下面三个随机值用于首次启动，后续重建容器时沿用原值。也可以把值写入 Git 忽略的 `deploy/.env`，启动时传入 `--env-file deploy/.env`。

```powershell
$env:NACOS_AUTH_TOKEN = python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(48)).decode())"
$env:NACOS_AUTH_IDENTITY_KEY = python -c "import secrets; print('easyjob-' + secrets.token_hex(8))"
$env:NACOS_AUTH_IDENTITY_VALUE = python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose -p easyjob-local-nacos -f deploy/compose.nacos.yml up -d --wait
```

打开 [Nacos 控制台](http://127.0.0.1:18848)，首次使用时初始化 `nacos` 管理员密码。确认旧版 Blog 和搜索索引进程已停止，在同一个 PowerShell 窗口执行以下命令。

```powershell
$env:EASYJOB_NACOS_ENABLED = 'true'
$env:EASYJOB_NACOS_USERNAME = 'nacos'
$secret = Read-Host 'Nacos 密码' -AsSecureString
$env:EASYJOB_NACOS_PASSWORD = [System.Net.NetworkCredential]::new('', $secret).Password
.\启动项目.cmd -Build
```

如果本机的 Nacos 已用 `temp/.env.nacos-local` 完成初始化，可用下面的方式重启容器，并直接读取本机已有的密码。

```powershell
docker compose --env-file temp/.env.nacos-local -p easyjob-local-nacos -f deploy/compose.nacos.yml up -d --wait
$env:EASYJOB_NACOS_ENABLED = 'true'
$env:EASYJOB_NACOS_USERNAME = 'nacos'
$entry = Get-Content temp/.env.nacos-local | Where-Object { $_.StartsWith('EASYJOB_NACOS_PASSWORD=') }
$env:EASYJOB_NACOS_PASSWORD = ($entry -split '=', 2)[1]
.\启动项目.cmd -Build
```

本地默认访问 `http://127.0.0.1:8848`，注册地址默认为 `127.0.0.1`，命名空间为 `public`，分组为 `EASYJOB`。接入已有 Nacos 时，可分别设置 `EASYJOB_NACOS_SERVER_URL`、`EASYJOB_NACOS_ADVERTISE_HOST`、`EASYJOB_NACOS_NAMESPACE` 和 `EASYJOB_NACOS_GROUP`。多个环境共用注册中心时，各环境用独立命名空间。服务账号需要对应分组的服务读写权限。

### Compose 部署

新环境用 `python scripts/deploy.py init-env` 生成部署密钥。已有环境在 `deploy/.env` 中补上三个 `NACOS_AUTH_*` 值。先启动 Nacos，初始化管理员密码，再在 `deploy/.env` 填写应用访问 Nacos 的账号和密码。

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yml -f deploy/compose.nacos.yml up -d --wait nacos
docker compose --env-file deploy/.env -f deploy/compose.yml -f deploy/compose.nacos.yml -f deploy/compose.nacos-discovery.yml up -d --build
```

Nacos 数据保存在 `nacos-data` 卷中。容器内用自己的 IP 注册。控制台和注册 API 只映射到宿主机回环地址。

### 验收和切回直连

在控制台的服务列表中选择 `public`，确认 `EASYJOB@@easyjob-blog` 有健康实例。Windows 本地可运行以下命令核对实例和索引服务状态，然后发布、修改、下架一篇测试文章，检查站内搜索结果。

```powershell
$login = Invoke-RestMethod 'http://127.0.0.1:8848/nacos/v3/auth/user/login' -Method Post -Body @{
    username = $env:EASYJOB_NACOS_USERNAME
    password = $env:EASYJOB_NACOS_PASSWORD
}
Invoke-RestMethod 'http://127.0.0.1:8848/nacos/v3/client/ns/instance/list?namespaceId=public&groupName=EASYJOB&serviceName=easyjob-blog' -Headers @{ accessToken = $login.accessToken } |
    Select-Object -ExpandProperty data
Invoke-RestMethod 'http://127.0.0.1:8084/actuator/health'
```

切回直连时，Windows 本地将 `EASYJOB_NACOS_ENABLED` 设为 `false` 后重启 Blog 和索引服务。Compose 使用原来的 `deploy/compose.yml` 重建这两个容器。

## 本次数据库升级

全库备份：`temp/backups/20261001-173447/easyjob.sql`。

执行了 `001_message_metadata.sql`、`002_agent_runs.sql`、`003_structured_memory.sql`。迁移保留原有业务数据，版本及校验和记录于 `agent_schema_migration`。以后升级前先备份，再在 `services/python-agent/` 执行：

```powershell
.\.venv\Scripts\python.exe -m app.migrate
```

## 已验证

- 前端页面与 `/api/article/list` 代理、Java 文章接口、Python `/health`。
- Checkpointer 真实写入暂停状态，重启 Redis 后由新进程读取并批准恢复，随后清理测试断点。
- DeepSeek 连接及 MainDecision 结构化决策、ES BM25 与 KNN 召回。
- 18 篇公开文章完成 HTML 分块重建，16 个有效文本块；2 篇无可索引正文。
- Python 163 项回归、Java Agent 相关 27 项回归通过。这些是功能测试，不代表模型回答准确率。

当前业务 Skill 定义目录 `services/python-agent/app/skills/definitions` 不存在，Skill 目录为空；本地工具与已配置的 GitHub MCP 工具已加载。

## 2026-10-03 更新

本地已执行到 `007_delivery_and_admission.sql`，包括文章关联会话、运行准入/SSE 补放和私信幂等字段。代码部署前必须在目标数据库执行同一迁移命令；启动脚本仍不替你执行迁移。

运行就绪检查使用 `http://127.0.0.1:8000/health/ready`，它会检查 MySQL、Redis、Checkpoint 所需的 JSON/Search 索引和 ES；`/health` 仅表示服务存活。此次改动及专项测试范围见 [可靠性与性能改进](runtime-reliability-20261003.md)。
