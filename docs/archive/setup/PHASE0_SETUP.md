# Phase 0 历史运行与验证

> 下文是上一批 Phase 0 的历史说明；当前入口已切换为 Main Agent + Subagent，部署请使用 [STAGED_SETUP.md](STAGED_SETUP.md)，不要按旧保存路径部署。

本次修改修复 RAG 契约、聊天入口、草稿恢复与记忆回查。Java→Python 服务间认证、持久运行锁、文章版本发布与完整阶段化工作流仍按统一路线后续实施。

## 部署顺序

1. 在 `python-agent` 目录安装 `requirements.txt` 中的依赖，Java 与前端一起更新。
2. 停止 Agent 请求，备份现有数据库，检查 `.env` 指向要升级的数据库。
3. 运行 `python -m app.migrate`，补齐 `ai_message.draft_article_id` 和 `citations`。脚本保留已存在的兼容字段，使用数据库锁、校验和与版本记录；DDL 中途失败可重复执行。
4. 启动 Python Agent，再启动 Java 网关。应用启动只检查字段，不自动执行 DDL；字段缺失或类型不兼容时会给出迁移提示。
5. 构建前端，确认普通聊天、检索引用、草稿确认/拒绝与历史引用展示。

Python 的历史、删除、取消接口新增 `user_id` 参数，配套 Java 已转发当前登录用户。此参数当前用于归属一致性检查，不替代可信服务间身份认证；Python 仍应通过现有 Java 网关访问。

## 回归命令

```powershell
# 在 python-agent 目录执行，测试不连接真实 MySQL、ES、Redis 或模型 API
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 在项目根目录执行，无需启动 Spring 或中间件
mvn -o '-Dtest=AgentProxyTests' test

# 在 frontend 目录执行
npm run build
```

草稿生成与审批使用独立 checkpoint 节点；确认时保存用户预览的版本，修改后再次确认。当前 Phase 0 保存服务仍是兼容 SQL 路径，使用 checkpoint 中固定的文章 ID 保证重复执行不新增文章；Java 内部保存 API 与 Markdown→HTML 闭环尚未接入。

## 兼容与回滚

旧的未完成草稿 checkpoint 使用旧节点结构，无法直接保证按新结构恢复。部署前处理完旧审批，或告知用户在新运行中重新生成并确认，禁止对旧预览进行无提示重建。已完成聊天记录无需转换。

数据库变更仅增加可空字段与迁移记录表；回滚程序时保留新增字段，不删除业务数据。若启用过新审批流程，回滚前同样先处理未完成审批。

记忆提取当前仍是进程内后台任务，只补充任务引用和异常收集；可靠队列投递、同会话并发执行控制与取消/保存的跨服务原子裁决尚未完成。本次离线回归不代替真实环境的中间件联调。
