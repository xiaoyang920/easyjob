# 本机开发服务

前端：http://127.0.0.1:3000；Java：http://127.0.0.1:8080；Python Agent：http://127.0.0.1:8000/health。

依赖：现有 MySQL 3306、Docker Redis Stack 缓存 6379/DB3、专用 Checkpointer Redis 6380/DB0、Elasticsearch 9.2.4（IK）9200、RabbitMQ 5672。

Checkpoint 容器为 `easyjob-checkpoint-redis`，数据卷为 `easyjob-checkpoint-data`，启用 AOF，端口仅映射到本机。镜像固定到已安装镜像的摘要。旧版 Windows Redis 缺少 Checkpointer 所需的 RedisJSON / RediSearch，当前使用 Docker 中的服务。已有 `redis-stack` 容器保留用于普通缓存。

## 启动

在仓库根目录执行：

```powershell
.\python-agent\.venv\Scripts\python.exe scripts\prepare-local.py
.\scripts\start-local.ps1
```

脚本沿用本机已安装的 Java、ES、RabbitMQ、Node；路径可以通过脚本参数覆盖。所有新进程在后台启动，日志保存到 `logs/`。ES 新启动时使用 1GB 堆。RabbitMQ 使用用户进程，无须修改 Windows 服务权限。Java 绑定回环地址，以避开系统网卡对 8080 的占用。

运行前需要已有 `python-agent/.env` 中的 MySQL/API 配置；新增密钥与 Redis 覆盖配置写入被 Git 忽略的 `python-agent/.env.runtime.local` 和 `temp/application-runtime.yml`。旧 `.env` 已被仓库跟踪，脚本不修改它。脚本不会自动执行数据库迁移或全文索引重建。

若修改 Java 代码，先停止项目 Java 进程再执行 `scripts/start-local.ps1 -Build`。需要重建旧文章的 HTML 文本块时，停止项目 Java 进程，再用 `scripts/start-local.ps1 -Reindex`；该选项会调用 embedding API。重建完成以 `logs/java.out.log` 中的“HTML块重建完成”为准，服务端口可能先于重建完成开放。

Java 后端需要重建时，启动器会对专用构建目录 `target/local-launcher` 执行 `clean package`，再复制生成的 JAR。删除 RPC 协议消息或 Java 源文件后，普通增量 `package` 可能保留旧的生成代码和类文件，导致编译错误或把已删除的类打入 JAR；清理专用构建目录可避免这类残留。源码、上传文件和数据库数据不受影响。

## 本次数据库升级

全库备份：`temp/backups/20261001-173447/easyjob.sql`。

执行了 `001_message_metadata.sql`、`002_agent_runs.sql`、`003_structured_memory.sql`。迁移保留原有业务数据，版本及校验和记录于 `agent_schema_migration`。以后升级前先备份，再在 `python-agent/` 执行：

```powershell
.\.venv\Scripts\python.exe -m app.migrate
```

## 已验证

- 前端页面与 `/api/article/list` 代理、Java 文章接口、Python `/health`。
- Checkpointer 真实写入暂停状态，重启 Redis 后由新进程读取并批准恢复，随后清理测试断点。
- DeepSeek 连接及 MainDecision 结构化决策、ES BM25 与 KNN 召回。
- 18 篇公开文章完成 HTML 分块重建，16 个有效文本块；2 篇无可索引正文。
- Python 163 项回归、Java Agent 相关 27 项回归通过。这些是功能测试，不代表模型回答准确率。

当前业务 Skill 定义目录 `python-agent/app/skills/definitions` 不存在，Skill 目录为空；本地工具与已配置的 GitHub MCP 工具已加载。

## 2026-10-03 更新

本地已执行到 `007_delivery_and_admission.sql`，包括文章关联会话、运行准入/SSE 补放和私信幂等字段。代码部署前必须在目标数据库执行同一迁移命令；启动脚本仍不替你执行迁移。

运行就绪检查使用 `http://127.0.0.1:8000/health/ready`，它会检查 MySQL、Redis、Checkpoint 所需的 JSON/Search 索引和 ES；`/health` 仅表示服务存活。此次改动及专项测试范围见 [可靠性与性能改进](runtime-reliability-20261003.md)。
