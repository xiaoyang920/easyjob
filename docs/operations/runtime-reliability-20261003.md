# 平台可靠性与性能改进（2026-10-03）

本文记录本次已落实的改动、运行边界和验证范围。测评原始记录在 `logs/evaluation/`，不将合成场景的流程通过率解释为答案准确率。

## 已实现

1. **HTML 安全处理**：普通文章保存/更新与 AI 草稿共用 Java 的 Jsoup 白名单；允许正文、表格和代码块，去除脚本、事件属性、危险 URL。前端文章详情和 AI Markdown 渲染后再通过 DOMPurify 清洗。相对上传路径仍可使用。
2. **文章索引一致性**：移除文章事务中的同步 ES 全文双写。文章变更与 Outbox 同事务提交，消费端同时同步正文分块、向量和全文索引，再确认任务；文章下架或删除同步删除两套索引。缓存失效继续在事务提交后进行。ES 属于最终一致，不能宣称跨 MySQL/ES 强一致。
3. **私信可靠投递**：服务器确定发送者身份；客户端生成 `client_message_id`，数据库以发送者和该 ID 的唯一索引防止重复保存/重复增加未读。发送和撤回先锁现有会话行；WebSocket 推送在提交后发生。新增按消息 ID 补拉接口，重连时刷新近期消息并补拉新增消息，前端按 ID 去重。更换客户端 ID 表示新消息。
4. **Agent 有界运行**：MySQL 中的控制行和租约在进程间统一限制全局、单用户并发和排队；同会话运行唯一限制继续有效。图内每次 LLM 调用前预留输入估算与最大输出额度，完成后以供应商 usage 结算；审批恢复继承已消耗额度。缺失 usage 或调用故障保守记账，不伪造实际使用量。
5. **流式连接与任务解耦**：后台 producer 持有 Agent 执行任务，将公开 SSE 数据帧保存至 MySQL，HTTP reader 仅订阅。页面关闭不自动取消后台运行；显式“停止”仍走取消接口。前端断线最多 3 次按事件游标重连，通过 GET 补放，不重发原聊天 POST。运行归属与 execution token 校验防止串号。
6. **前端加载与长聊天**：Element Plus 组件和图标按需导入；文章详情的代码高亮只加载常用语言。聊天首批渲染最近 80 条，按需向前加载 60 条；历史消息仍保留，不改变数据库记录或 Agent 输入窗口。
7. **运维与回收**：独立存活和依赖就绪探针；内部接口返回运行、排队、后台任务与索引任务的聚合数量和积压时间。每小时有界清理终态事件/历史任务；不清理待审批运行及 checkpoint。

## 默认边界

| 设置 | 默认值 | 说明 |
|---|---:|---|
| AGENT_EXECUTION_GLOBAL_LIMIT | 8 | 所有 Python worker 共用 |
| AGENT_EXECUTION_USER_LIMIT | 2 | 同用户不同会话 |
| AGENT_EXECUTION_QUEUE_LIMIT | 16 | 等待队列容量 |
| AGENT_EXECUTION_WAIT_SECONDS | 10 | 超时返回 429 和 Retry-After |
| AGENT_RUN_TOTAL_TOKEN_BUDGET | 524288 | 一次运行的累计图内 LLM 预算，包含审批恢复 |
| AGENT_STREAM_RETENTION_DAYS | 7 | 仅终态运行的 SSE 事件可回收 |
| 已完成后台任务/索引任务 | 30 天 | 每次最多 500 条 |
| dead 任务 | 90 天 | 每次最多 500 条 |
| Java SSE 异步执行器 | 8/32/64 | 核心线程/最大线程/队列 |

累计 Token 预算不是单次上下文窗口，且不覆盖 embedding、rerank、图片预处理与后台记忆提取。输入计数采用本地估算，供应商实际 usage 可能不同；调用前预留不能证明实际账单绝不超过估算。现有请求输入预算和压缩策略继续生效。

## 数据库与接口

先运行 `cd python-agent; .\.venv\Scripts\python.exe -m app.migrate`。新增 `007_delivery_and_admission.sql` 创建 admission 控制行/租约表、SSE 帧表，并增加私信幂等字段与唯一索引。迁移已经在本地执行；迁移器校验已执行文件的 checksum。

- `GET /health`：轻量存活检查。
- `GET /health/ready`：MySQL、普通 Redis、Checkpoint Redis JSON/Search 索引、Elasticsearch 检查；失败为 503，结果缓存 5 秒，单依赖超时 2 秒。
- `GET /internal/metrics`：要求现有服务身份认证；只返回聚合数据，不返回用户消息或记忆内容。
- `GET /api/agent/runs/{run_id}/events?after={event_id}`：用户认证后补放自己的运行事件；Java 转发。
- `GET /api/chat/messages/after`：会话成员按消息游标补拉，分页大小限制 1～100。

不要向前端暴露 `AGENT_SERVICE_KEY`；metrics 不通过普通公开页面开放。

## 恢复边界

HTTP 断线后后台继续执行。已完成运行即使事件被回收，也能从运行账本重建最终回复/审批状态。服务进程崩溃时，已经持久化的事件仍可补放，但进行中的 LLM 调用不自动重做；期限到达后标记失败。此实现不能称为任意进程崩溃后从 Token 中途恢复。

后台记忆任务和索引任务采用现有主键行的 `FOR UPDATE SKIP LOCKED` 领取与租约 token；租约到期后其他 worker 可重新领取，旧 token 不能提交。不会对不存在记录做锁定查询，也不使用覆盖待领取范围的批量锁。

引用修正最多一次；子代理修正后仍失败时清除该产物的正文和证据，以 `invalid_citation` 观察反馈 Main，阻止依赖任务执行，同时保留独立任务的成功结果。无效答案依赖进入最多两次的结构化动作校验。执行边界收尾保留已验证的相关资料，明确说明不足，不假称完整完成。待审批草稿即使修改前后内容一致，仍保持待审批；内容不变则哈希不变，内容有变时旧审批失效。

## 验证

- Python：345 项测试全部通过，含累计预算、断线后 producer、持久化补放、就绪失败、依赖修正、漏引用修正，以及子代理失败分支隔离。
- Java：84 项测试全部通过，含 HTML 清洗、事务提交前无推送、重复私信、全文索引失败重试。
- 前端：40 项测试通过；类型检查和生产构建通过；浏览器确认首页及登录弹窗组件/图标完整。
- 真实本地 MySQL/Redis 专项：15/15，覆盖限流、排队取消、过期租约、断线后一次保存与补放。报告：`logs/evaluation/runtime-fault-20261003-214051.json`。执行图使用确定性替身，不包含付费模型调用，也不等同真实杀进程试验。
- 真实私信 API/数据库专项：9/9，包含 10 个并发同幂等 ID 只产生一条消息、未读只增一次、游标分页与撤回后不重复发送。报告：`logs/evaluation/message-delivery-20261003-211928.json`。
- 第一次完整真实模型回归：136 场景/183 轮，132/136 流程契约通过；保留 4 条失败原始记录。修正部分资料收尾、答案无效依赖和漏引用问题；另一条是已无代码草稿修订无变化时测试误判。原始报告：`logs/evaluation/scenarios-optimized-20261003/report.md`。
- 修正后相关类别重测：联网、无结果、草稿共 20/20。报告：`logs/evaluation/scenarios-optimized-followup-20261003/report.md`。此结果不能和原报告拼成一次 136/136 测评。
- 第二次完整真实模型回归：136 场景/183 轮，135/136 流程契约通过，0 超时；并发 4。唯一失败是子代理局部引用修正失败后主流程抛异常，已修正为分支隔离和失败观察。报告：`logs/evaluation/scenarios-optimized-final-20261003/report.md`。保留此失败，后续委派重测单独记录，不改写原报告。
- 子代理恢复修正后重测：6 个委派场景各重复 3 次，18/18 流程契约通过，0 超时，Token usage 完整计量 18/18；并发 3。报告：`logs/evaluation/scenarios-delegate-recovery-20261003/report.md`。这是相关功能的专项回归，不是又一次完整 136 场景测评。

生产构建单个 JS 文件：主入口从约 1179 KB 降到 119.47 KB，文章详情从约 1070 KB 降到 172.22 KB；这是未压缩单文件大小，不代表总下载量或页面耗时同比下降。文章编辑器路由仍约 821 KB，按路由加载。

## 复现

```
# Python
cd python-agent
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m evaluation.scenarios live --include-web --concurrency 4 --allow-writes --fail-on-contract --output ../logs/evaluation/scenarios-optimized-final-20261003

# 真实基础设施专项；先确保没有其他 Agent 运行
cd ..
.\python-agent\.venv\Scripts\python.exe scripts/runtime-fault-check.py
.\python-agent\.venv\Scripts\python.exe scripts/message-delivery-check.py
```

评测数据是预先编写的合成场景，答案事实质量、每条引用是否支持结论等仍需人工审阅。第三方联网结果和模型输出会随时间变化，应保留原始输出、版本与失败分母。
