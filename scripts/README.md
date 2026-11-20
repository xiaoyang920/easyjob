# 项目脚本

在仓库根目录运行下列命令。需要 Agent 依赖的 Python 脚本用 `python-agent` 的虚拟环境执行。

| 位置 | 用途 | 示例 |
| --- | --- | --- |
| `scripts/` | 启动、重启、配置生成和部署入口 | `powershell -File scripts/start-local.ps1 -Check` |
| `scripts/migrations/` | 指定功能的增量迁移入口 | `python scripts/migrations/migrate-product-features.py` |
| `scripts/checks/` | 功能冒烟、回归和跨服务验收 | `python scripts/checks/excel-export-smoke.py --help` |
| `scripts/benchmarks/` | 检索、向量化和秒杀性能实验 | `powershell -File scripts/benchmarks/embedding-pool-benchmark.ps1` |
| `scripts/diagnostics/` | 会话、画像和模型决策诊断 | `python scripts/diagnostics/decision-contract-replay.py` |

跨服务测试的固定数据和配套容器位于 `tests/integration/`。迁移 SQL 仍由 `services/python-agent/migrations/` 管理，`scripts/migrations/` 提供命令入口。
