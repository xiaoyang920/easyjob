# EasyJob

EasyJob 是一个技术博客平台。Java 服务负责博客业务、认证、网关、文章索引和 Excel 导出，Python Agent 提供文章问答、写作辅助和流式回复，Vue 前端提供阅读、创作与管理后台。

- [文档总目录](docs/README.md)
- [项目介绍与环境配置](docs/architecture/project-overview.md)
- [本地启动](docs/operations/local-startup.md)
- [Excel 导出](docs/operations/excel-service.md)
- [脚本索引](scripts/README.md)
- [当前运行架构](docs/architecture/current-runtime.md)
- [Trace ID 手敲教程](docs/learning/traceid/README.md)

## 本地启动

准备依赖和本地配置后，在 Windows 上从仓库根目录运行 `.\启动项目.cmd`。前端端口为 `3000`，Excel 服务监听本机 `8083`，日志位于 `logs/excel.out.log` 和 `logs/excel.err.log`。 [环境配置](docs/architecture/project-overview.md) · [本地前端](http://127.0.0.1:3000)

如果现有数据库还未应用 `032_excel_export_job.sql`，先停止 Blog、Python Agent 和 Excel，再运行 `.\启动项目.cmd -Migrate`。启动器默认启动 Excel，调试时可用 `.\启动项目.cmd -SkipExcel` 跳过。

## 社区统计导出

管理员进入「管理后台 → 社区数据」，选择日期范围和数据来源后点击「导出 Excel」。Blog 检查权限并查数，Excel 服务按页读取数据并填充「每日统计」工作表。前端通过 WebSocket 接收完成通知，断线时轮询，成功后通过鉴权接口下载。部署配置与验收命令见 [Excel 导出文档](docs/operations/excel-service.md)。

## 仓库目录

| 路径 | 内容 |
| --- | --- |
| `services/blog-service/` | Blog 业务服务，包含独立的 `pom.xml`、源码和测试 |
| `services/gateway/`、`services/auth-service/`、`services/excel-service/` | 网关、认证和 Excel 导出服务 |
| `services/search-index-service/` | 消费文章索引任务，生成并更新全文索引和向量索引 |
| `services/python-agent/`、`frontend/` | Python Agent、Vue 前端 |
| `auth-common/`、`search-index-common/`、`contracts/` | Java 共用身份代码、文章索引契约、跨语言 RPC 契约 |
| `deploy/`、`scripts/`、`tools/` | 容器部署、维护与验收脚本、本机工具 |
| `tests/` | 跨服务集成测试、测试设施和脚本测试 |
| `docs/` | 架构、接口、运维、学习和历史文档 |

各应用的单元测试随应用维护。截图、临时文件、日志和备份分别放在 `artifacts/`、`temp/`、`logs/`、`backups/`。

仓库根目录的 `pom.xml` 聚合 `services/` 下的五个 Java 服务。在根目录运行 `mvn package` 可一起构建，单独构建 Blog 用 `mvn -f services/blog-service/pom.xml package`。Python Agent 使用自己的虚拟环境和依赖文件。
