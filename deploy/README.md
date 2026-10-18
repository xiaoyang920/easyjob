# 容器部署与备份恢复

此配置启动独立的单机环境，不接管 Windows 一键启动的服务。MySQL、两个 Redis、ES、RabbitMQ、Consul、Java、Python、网关和前端通过容器网络互通；只向本机发布网页端口 `8088`。Java/Python 使用共享只读/读写上传卷、相同服务密钥及 Consul 发现，不向公网暴露 RPC 和依赖端口。

## 启动

在根目录执行（Windows 可用 `python-agent/.venv/Scripts/python.exe` 代替 `python`）：

```sh
python scripts/deploy.py init-env
# 编辑 deploy/.env，填写模型密钥及邮箱设置。生成的本地密钥不会打印，也不会提交。
python scripts/deploy.py validate
docker compose --env-file deploy/.env -f deploy/compose.yml up -d --build --wait --wait-timeout 600
```

首次启动在空数据库中导入 `deploy/mysql/schema.sql`，再执行现有幂等迁移。已有数据库只执行增量迁移，不重新导入基础结构。基础结构不包含用户数据、管理员密码或真实账号；注册后角色仍按原业务规则管理。迁移任务失败时业务服务不启动。ES 包含与服务器版本一致的 IK 插件、技术词典和查询同义词。

启动顺序依据依赖健康状态和一次性任务成功状态，而不是固定等待秒数，参见 [Docker Compose 启动依赖文档](https://docs.docker.com/compose/how-tos/startup-order/)。镜像构建需要网络，模型、邮箱功能需要自己的有效配置；未配置精排/联网密钥时沿用现有降级行为。`--wait` 检查健康不等同于完成真实模型评测。

前端地址为 `http://127.0.0.1:8088`。更改 `WEB_PORT` 可以并行启动演练环境。跨机器访问应显式配置绑定地址、域名与 HTTPS；当前默认入口仅供本机访问。Consul 的 dev 模式用于单机环境，生产集群需另行配置持久化、ACL 与 TLS。

## 一致性备份

```sh
# 默认只显示计划，不停止服务
python scripts/deploy.py backup --directory backups/2026-10-17
# 执行：短暂停止本 Compose 项目的网页、网关及业务写入，完成后恢复原先运行的服务
python scripts/deploy.py backup --directory backups/2026-10-17 --execute
python scripts/deploy.py verify --directory backups/2026-10-17
```

备份包含事务一致的 MySQL SQL、上传文件、Redis Stack Checkpoint RDB、ES 文件系统快照及 SHA-256 清单。暂停写入后再导出，保证引用的图片和内容属于同一时间边界；执行中的 Agent 可能按现有关闭逻辑记录为中断，可通过失败恢复入口处理。不会停止本机其他服务。普通 Redis 缓存和 MQ 不复制，恢复后缓存冷启动，可靠任务依靠数据库 Outbox 重新投递；登录续签凭证可能需要重新建立。

每个项目使用互斥文件防止同时备份；异常保留未完成目录，缺少完整清单的备份不能恢复。备份完成并校验后删除本次临时 ES 快照，历史备份目录不自动删除。备份包含私有对话、草稿与图片，应存放于受控目录，按自己的留存周期离机保存。密钥和 `.env` 不进入备份。

## 恢复演练

恢复必须使用**从未使用过的新项目名**，检查包括停止的容器和已存在的数据卷。程序拒绝覆盖来源项目或已有目标，不执行删除旧环境的命令。

```sh
python scripts/deploy.py --project easyjob-restore-20261017 restore --directory backups/2026-10-17
# 在 deploy/.env 中设置不同 WEB_PORT，避免来源环境的网页端口冲突，再执行
python scripts/deploy.py --project easyjob-restore-20261017 restore --directory backups/2026-10-17 --execute
```

程序先校验清单、哈希及归档路径，拒绝目录穿越、软硬链接与特殊文件；只允许上传、Checkpoint 和 ES 快照内容。随后恢复新卷、导入新数据库、恢复 ES 索引，再启动应用。旧项目和数据卷保留。演练后检查文章/图片、关键词和语义检索、草稿箱、历史对话及待审批草稿；审批和保存仍重新验证当前权限与来源版本。

备份恢复工具仅操作这份 Compose 配置创建的环境，不直接适用于既有 Windows 本机数据库。迁移本机数据时，应先做独立备份并导入新容器环境，再使用该工具。
