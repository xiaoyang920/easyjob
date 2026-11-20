# 社区统计 Excel 导出

管理后台的「社区数据 → 导出 Excel」提交一个后台任务，沿用页面的近 7、30 或 90 天和数据来源。导出文件只有「每日统计」工作表，包含日期、新增用户、首次发布文章、有效阅读秒数和有效阅读用户数。没有数据的日期填零。

浏览器经网关调用 Blog。Blog 用当前登录用户检查 `statistics.read`，按北京时间固定包含今天的日期区间，然后把任务交给 Excel 服务。Excel 每次按一个日期子区间向 Blog 取数，并用同一个 EasyExcel writer 在同一模板上连续填充。每页有独立的只读事务，区间固定，执行期间新增的业务数据仍可能被后续页读到。

任务写入最终状态后，Excel 服务调用 Blog 的内部接口，Blog 通过现有 `/ws/chat` 连接向任务提交者发送 `excel_export_finished`。管理后台收到匹配的 `jobNo` 后立即查询状态，成功后鉴权下载。断线时每 1.5 秒查询，重连后立即补查。连接正常时保留每 15 秒一次的状态查询，覆盖通知发送失败或丢失。

## 本地启动

本机启动器默认启动 Excel。若数据库还没有 `excel_export_job` 表，先停止本机的 Blog、Agent 和 Excel，再从仓库根目录执行带迁移的命令。

```powershell
.\启动项目.cmd -Migrate
# 后续启动
.\启动项目.cmd
# 调试时跳过启动 Excel
.\启动项目.cmd -SkipExcel
```

启动器从现有本地 MySQL 配置生成被 Git 忽略的 `temp/excel-runtime.yml`，首次生成服务密钥，后续复用。Blog 和 Excel 读取同一文件。启动器检查两端是否接受该密钥，以及 Excel 能否查询任务表。如果已有 Blog 进程尚未加载配置，执行 `./scripts/restart-java.ps1` 后再运行启动器。Excel 监听本机 8083，日志在 `logs/excel.out.log` 和 `logs/excel.err.log`，文件默认写入 `temp/excel-exports`。

如需单独启动 Excel，先用启动器准备好配置并启动 Blog，然后在仓库根目录执行：

```powershell
mvn -f services/excel-service/pom.xml package
& 'D:\jdk\bin\java.exe' -jar services/excel-service/target/easyjob-excel-0.0.1-SNAPSHOT.jar --spring.config.additional-location=file:./temp/excel-runtime.yml
```

## 服务间通信

| 调用方向 | 内部 HTTP 接口 | 作用 |
| --- | --- | --- |
| Blog → Excel | `/internal/excel/jobs` 及其子路径 | 提交、查状态、获取生成文件。 |
| Excel → Blog | `GET /internal/excel/community-daily` | 按页读取统计数据，Blog 复核任务提交者的统计权限。 |
| Excel → Blog | `POST /internal/excel/job-finished` | 最终状态写入 MySQL 后通知 Blog，由 Blog 通过 `/ws/chat` 推给提交者。 |

两端使用相同的 `X-Excel-Key`，内部路径由网关拒绝对外访问。本地互访用 8080 和 8083，Compose 中使用 `http://blog:8080` 和 `http://excel:8083`。

## 端到端验收

另开一个 PowerShell 窗口执行。脚本会提示输入管理员密码。也可以提供当前登录会话的 `EXCEL_ADMIN_TOKEN` 环境变量。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8083/actuator/health'
python scripts/checks/excel-export-smoke.py --base-url http://127.0.0.1:8090 --email YOUR_ADMIN_EMAIL --days 30 --source business --output temp/community-daily-check.xlsx
```

脚本并发提交两次相同请求，确认只返回一个任务号，再轮询、检查匿名下载被拒绝、下载文件并校验工作表、连续日期和数值列。默认每页 10 天，30 天会读取三页。Excel 服务日志中可按任务号查找失败记录。单独执行 `mvn -f services/excel-service/pom.xml test` 可用 11、11、8 行验证三次连续填充，逐行比较数值。

页面验收可从 `http://127.0.0.1:3000` 登录管理员账号，进入「管理后台 → 社区数据」，选择来源和日期范围，点击「导出 Excel」，等待浏览器下载。

## Docker Compose

新环境运行 `python scripts/deploy.py init-env` 会生成 Excel 库密码和服务间密钥。现有 `deploy/.env` 追加独立生成的 `EXCEL_DB_PASSWORD` 与 `EASYJOB_EXCEL_SERVICE_KEY`，分别至少 32 字符，再使用原 Compose 项目启动。

```powershell
python scripts/deploy.py validate
docker compose --env-file deploy/.env -f deploy/compose.yml up -d --build --wait --wait-timeout 600
```

迁移完成后，`database-permissions` 给 `ej_excel_runtime` 授予任务表权限。Excel 容器通过内部网络访问 Blog，生成文件落在 `excel-exports` 卷，随部署备份保存。多实例部署时，所有 Excel 实例须挂载同一个可原子重命名的文件目录。当前版本保留任务和导出文件，磁盘和任务表容量随导出累积。

## 接口和任务字段

| 字段或接口 | 用途 |
| --- | --- |
| `POST /api/admin/statistics/export-jobs` | 接收 `requestId`、`days` 和 `source`，返回任务。相同用户和请求号重试返回原任务，改用其他天数或来源会返回 HTTP 409。 |
| `GET /api/admin/statistics/export-jobs/{jobNo}` | 查询自己的任务状态。 |
| `GET /api/admin/statistics/export-jobs/{jobNo}/file` | 检查当前统计权限和任务归属后下载已完成的 XLSX。 |
| `owner_id, request_id` | 联合唯一键。请求号由前端为每次新导出生成，提交结果不确定时用原号重试。 |
| `job_no` | Excel 服务生成的任务主键，用于查询和下载。 |
| `from_day, to_day, source` | 提交时固定的统计日期和来源，重试时继续使用这组条件。 |
| `status, attempts, available_at` | 排队、执行、成功或失败。每次抢占增加尝试次数，重试前等待，最多执行三次。 |
| `lease_token, lease_until` | 每次抢占生成独立令牌，租约默认 60 秒，每页读取前续期。租约过期后另一实例可以抢占，旧令牌无法续期或提交结果。 |
| `row_count, file_name, last_error` | 成功后记录数据行数和实际文件名，失败时记录可展示的错误码。 |

Excel 扫描候选任务后通过条件更新抢占。写入以本次租约命名的临时文件，完成后原子重命名，再以相同租约更新任务状态。进程在完成前退出时，下次执行从第一页重新生成。
