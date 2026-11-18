# EasyJob

EasyJob 是一个技术博客平台。Java 服务负责博客业务、认证、网关、文章索引和 Excel 导出，Python Agent 提供文章问答、写作辅助和流式回复，Vue 前端提供阅读、创作与管理后台。

## 本地启动

准备依赖和本地配置后，在 Windows 上从仓库根目录运行以下命令。 [环境配置](docs/architecture/project-overview.md)

```powershell
.\启动项目.cmd
```

如果现有数据库还未应用 `032_excel_export_job.sql`，先停止 Blog、Python Agent 和 Excel，再运行 `.\启动项目.cmd -Migrate`。启动器默认启动 Excel，调试时可用 `.\启动项目.cmd -SkipExcel` 跳过。

| 服务 | 目录 | 本地端口 |
| --- | --- | --- |
| Vue 前端 | `frontend/` | `3000` |
| API 网关 | `gateway/` | `8090` |
| Blog | `src/` | `8080` |
| 认证 | `auth-service/` | `8081` |
| Excel 导出 | `excel-service/` | `8083` |
| Python Agent | `python-agent/` | `8000` |

启动完成后打开 [本地前端](http://127.0.0.1:3000)。Excel 服务日志位于 `logs/excel.out.log` 和 `logs/excel.err.log`。

## 社区统计导出

管理员进入「管理后台 → 社区数据」，选择日期范围和数据来源后点击「导出 Excel」。Blog 检查权限并查数，Excel 服务按页读取数据并填充「每日统计」工作表。前端通过 WebSocket 接收完成通知，断线时轮询，成功后通过鉴权接口下载。部署配置与验收命令见 [Excel 导出文档](docs/operations/excel-service.md)。

## 项目文档

- [文档总目录](docs/README.md)
- [项目介绍与环境配置](docs/architecture/project-overview.md)
- [本地启动](docs/operations/local-startup.md)
- [Docker Compose 部署](docs/operations/deployment.md)
- [当前运行架构](docs/architecture/current-runtime.md)
- [Trace ID 手敲教程](docs/learning/traceid/README.md)

项目说明、接口参考、学习资料和论文材料已统一放在 docs 下。运行时技能文件和工具约定的配置文件保留原位置。
