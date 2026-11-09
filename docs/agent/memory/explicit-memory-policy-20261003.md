# 长期记忆收敛与历史事件归档

## 当前策略

当前长期记忆只包含用户画像、有效约束和用户明确确认的决策。Main 使用现有结构化响应的 `memory_changes` 提交明确变更，后端继续校验当前用户原话、身份、作用域和有效运行。普通咨询、工具结果、助手回答不会通过后台提取成为长期记忆；普通对话仍保留在会话消息和增量摘要中。

删除正常对话结束后的提取入队入口，退役每六轮及关键词提取判断。旧 `memory_extract` 待处理任务直接结束，不读取聊天，不调用模型，不写入记忆。历史提取兼容方法保留为空操作，避免旧调用方重新开启提取。

ES 查询只选 decision，MySQL 回查只接受当前用户、当前适用范围内的 active decision；因此旧事件即使还留在 ES 或数据库标为 active，也不能召回。约束继续通过启动上下文按范围加载，画像继续读取独立结构字段。

管理页默认只展示约束和决策；旧事件使用“旧事件（归档）”独立分页，只能查看和删除。后端拒绝编辑或重新启用旧事件，不仅依赖前端隐藏按钮。没有批量删除用户原有记录，也没有改变全量会话保存。

## 验证结果

2026-10-03 已重新打包并启动 Java/Python 服务，前端类型检查和生产构建通过。

- Python 单元回归：341 项通过；Java：84 项通过；前端：40 项通过。
- 真实模型记忆专项：10 个预先编写的合成场景，28 轮提问，34 次模型调用，10/10 自动检查通过。覆盖画像更新、有效约束、决策召回、取消与改写、跨会话隔离，以及连续普通问答不新增任何记忆、不创建提取任务。结果为本次有限场景的自动检查，不代表所有自然语言场景的语义正确率。
- 本地真实 MySQL/Java API 专项：8 项通过，验证默认分页排除旧事件、归档独立分页、拒绝重新启用、可删除、旧候选经数据库回查被排除及退役入口不创建任务。该专项模拟了过期 ES 候选，不调用付费模型或 embedding；ES 类型过滤由单元回归验证。
- 评测账号及专项夹具均已清理，用户原有记录未删除。

可复现入口：`python -m evaluation.scenarios live --categories memory --concurrency 2 --allow-writes --fail-on-contract --output <新目录>`（在 python-agent 目录运行），及 `python-agent/.venv/Scripts/python.exe scripts/explicit-memory-check.py`（仓库根目录运行）。前者需要运行中的本地服务并调用真实模型。

本次报告：`logs/evaluation/explicit-memory-20261003/summary.json`、`logs/explicit-memory-storage.txt`；单元结果见 `logs/explicit-memory-tests.txt`、`logs/explicit-memory-java-tests.txt` 和 `logs/explicit-memory-frontend-tests.txt`。
