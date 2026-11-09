# 明确继续上次任务：同 run 检查点恢复

## 入口和存储职责

用户点击“继续上次未完成任务”调用 `POST /runs/{run_id}/recover`。普通聊天和文章问答中，只输入“继续”“重试”“继续上次任务”或“继续上次未完成任务”（可带末尾句号/感叹号）时，`/chat` 与 `/chat/stream` 也先选择当前会话最新的未完成 run，进入同一个恢复入口。识别在后端完成，不让 Main 决定是否读取检查点。

活动 run 直接重新订阅原有事件流，不占用新的执行 admission、不启动另一个图。失败、过期或用户手动停止的 run 通过校验后，在 MySQL 事务中认领新的 execution token；使用原 `run_<run_id>` Redis thread 和 `graph.ainvoke(None, config)` 继续。同步非流式接口遇到仍在运行的任务返回冲突，避免提前结算。

“继续，但改成英文”等带新要求的消息，以及附带图片、选文引用、编辑器快照或写作上下文的消息，仍创建新 run。没有旧 run 或旧任务已成功完成时，“继续”作为普通后续消息交给 Main。待确认草稿要求使用原审批按钮；未完成任务的检查点不可恢复时明确返回冲突，保留输入，不悄悄另起任务。

流式恢复使用 `__RECOVERED_RUN__` 通知前端更新原任务。临时“继续”输入不新增聊天历史，原问题和已完成活动保留，避免刷新后出现重复回答。手动停止后会立即重新查询检查点可用性，符合条件时显示恢复按钮。

Redis 保留 LangGraph 最近状态和待执行写入，MySQL 保留运行台账、结果、使用量和节点内并发子任务缓存。没有存储迁移，也没有任意历史版本回退。

## 可恢复范围

- 必须是当前用户、当前会话的最新 run，台账为 failed、expired 或 cancelled，没有活动替代 run。用户可在再次停止或失败后显式继续；recovery_count 记录次数，原模型使用量和图状态中的轮次预算继续累计，不自动重试。
- 检查点身份必须完整匹配 run_id、user_id、conversation_id。
- `snapshot.next` 恰好包含一个节点：main_agent、execute_tool、main_retrieve 或 main_delegate。
- Main 可以继续新一轮决策；直接工具只允许注册的公开只读能力；委派仅允许 search/analysis。节点内已完成子任务继续使用原 MySQL 缓存。
- 已有公开文章证据必须保留 sourceHash，并重新验证当前可见性和版本。网页证据最长一天，年龄使用原结果 source_run_updated_at 或原 run.created_at，不能使用恢复时更新的台账时间。
- 校验同时覆盖 task_results、previous_run.reusable_results、顶层 citations 和 delivery_evidence；用户资料、有效约束也必须仍与当前值一致。

普通新 run 的 MySQL 结果复用也使用原 run.created_at 作为缺少显式源时间时的保守下界，避免恢复更新 updated_at 后让旧网页重新获得一天有效期。长时间运行中新检索的资料可能因此提前失效；安全地重新检索优于扩大旧结果有效期。

委派节点内尚未进入父检查点的 MySQL 子任务缓存，在加载时也检查网页年龄：使用原 source_run_updated_at 或 artifact.updated_at，超过一天仅让该子任务重新执行，其他可用缓存继续保留。

## 拒绝条件

END、多待执行节点、审批 interrupt、State 内 cancelled 标记、已完成业务、已保存草稿或已受理 draft_commit 均不能走此入口。台账 cancelled 表示停止执行，可以恢复到之前有效的只读检查点；State 内 cancelled 表示图内已处理取消，例如拒绝草稿，不能将其抹除后重放。草稿审批仍使用原审批协议。

包含 editor、draft、memory 私有状态或待写记忆的快照拒绝恢复。Main 对应的 memory-write durable job 已存在时也拒绝，避免入队已提交但节点输出未进 Redis 的情况下重复决策。

缺少身份、schema 不兼容、检查点不可读、权限/源版本变化、网页过期、缺少 sourceHash，以及已完成但缺少可重验资源身份的公共查询结果（例如 get_article_comments）均保守拒绝。界面只在真实检查点校验通过时显示可恢复。

历史聊天文本仍是对话上下文，不会因为恢复而被登记成新的可复用证据。

## 并发和故障边界

认领、取消、过期和业务检查点写入通过同一 MySQL run 行锁互斥。检查点 aput/aput_writes 在持锁期间校验 execution token；旧执行代次不得覆盖恢复后的 Redis。父子 namespace 使用同一 run 身份。业务 thread 缺少 token 或 run_id 时拒绝写入。

持锁期间的 Redis 写入限时 5 秒；超时取消写入并退出事务，释放行锁。此限时不替代数据库本身的连接和锁等待超时。Redis 客户端必须遵守 asyncio cancellation；跨 MySQL/Redis 没有分布式原子提交，失败时以拒绝恢复为原则。

节点从有效运行 config 获取新 token，用于 memory 入队和其他节点内业务动作。双击由 claim_recovery 的事务检查收敛为一次认领，后续请求可以重连活动执行或得到冲突。停止请求只取消它在事务中终止的 execution token，延迟返回的旧停止请求不会中断新恢复的执行器；token 不出现在公开响应中。

## 离线验证

专项用例位于 `python-agent/tests/test_checkpoint_recovery.py`，使用真实 StateGraph 和 LatestRunRedisSaver wrapper，底层是 InMemorySaver/fake，不连接 Redis/MySQL 或模型。覆盖 None 恢复保留已完成检索、父子 namespace、旧写入 fencing、双击认领、活动重连、超时释放、审批/草稿/取消拒绝，以及权限和网页时效。

全套运行入口：`python-agent/.venv/Scripts/python.exe scripts/run-agent-offline-tests.py`。该脚本先安装不可移除的 socket/DNS audit guard；仅放行 Windows asyncio 自身的本地 socketpair。真实 Redis Stack、MySQL 行锁和生产模型不在此轮离线验证范围。

2026-10-21 本轮验证记录：补充纯“继续”路由、手动停止恢复及执行代次隔离测试后，Python 全套 938 条：929 条通过、9 条跳过，0 失败/错误，网络拦截审计记录为空。日志为 `checkpoint-continuation-offline-tests.log`。前端构建成功，agent-stream 29 条通过，新增恢复交互单元测试 5 条通过。未重启服务，未调用真实模型；真实 Redis/MySQL 集成验证仍不在本轮范围内。
