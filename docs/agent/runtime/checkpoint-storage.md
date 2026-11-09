# Agent 检查点存储

新运行使用 `AsyncShallowRedisSaver`：每个 run 的主图以及各子图命名空间各保留最新完整状态。仍然在图执行步骤之间持久化，不等待整个 run 结束。并发子任务由 `main_delegate` 汇总后提交主图状态；节点中途退出时，已完成只读任务通过原有 MySQL `agent_task_artifact` 校验并复用。

运行过程、消息、错误和最终交付仍在 MySQL。浅检查点用于最近位置恢复，不提供任意历史检查点回退；`alist` 也只允许指定运行，不能用它代替运行历史查询。

## 兼容和中间写入

依赖固定为 `langgraph-checkpoint-redis==0.5.2`。该版本浅存储使用线程级中间写入注册表，本项目读取时额外匹配 thread、namespace 和 checkpoint ID，避免重放旧步骤的结果或错误。Redis 故障继续抛出，不能把读取失败伪装为没有待执行记录。

不在每次覆盖状态时删除中间写入，防止并行任务和 interrupt 的必要记录被提前删除。中间写入仍随本次运行保留到终态清理；因此减少的是重复完整快照，不意味着一个 run 在 Redis 中只有一个 key，也不意味着总占用与步骤数完全无关。大检索原文与草稿的进一步外置属于后续优化。

路由按整个 run 选择格式，子图沿用父图选择。重启后先识别浅存储根键，否则查找旧格式根检查点。已存在的旧运行继续使用原有 `AsyncRedisSaver`，待审批和失败恢复不进行破坏性转换；新运行才使用浅存储。旧运行此前占用的内存会随终态清理逐渐释放。

## 保留期

| 状态 | 默认保留期 |
| --- | --- |
| succeeded | 最后更新时间起 1 天 |
| failed / cancelled / expired | 最后更新时间起 7 天 |
| running / awaiting_approval | 不在检查点清理中删除，先按运行和审批期限结束状态 |

配置 `AGENT_CHECKPOINT_SUCCESS_RETENTION_DAYS=1` 和 `AGENT_CHECKPOINT_FAILURE_RETENTION_DAYS=7`，均至少 1 天。旧变量 `AGENT_CHECKPOINT_RETENTION_DAYS` 作为失败类保留期的兼容后备值；若已有环境显式设为 30，需要更新新变量才会使用 7 天。

清理仍通过持久化后台任务执行。筛选和执行共享同一保留规则；执行时在事务内锁定对应 `agent_run`，再次检查归属、终态和年龄后删除两个格式的检查点及中间写入。恢复入口也锁同一运行行，避免“检查已结束后、实际删除前”运行被恢复的竞争。运行中和待审批状态没有统一短 Redis TTL，不因用户暂时离线丢失审批。

清理任务按 run 和最后更新时间去重。运行恢复后再次结束，可以生成新一轮清理任务，不会被上一次因恢复而跳过的已完成任务永久挡住。

## 验证

```powershell
# python-agent 目录，不请求模型；使用当前配置的 Redis Stack，夹具线程独立且自动清理。
$env:EASYJOB_CHECKPOINT_REDIS_TEST='1'
.venv/Scripts/python.exe -m unittest discover -s tests -p test_checkpoint_store.py -v
# 项目根目录：本机临时用户/会话验证 MySQL 保留规则、状态和清理。
python-agent/.venv/Scripts/python.exe scripts/optimization-check.py
```

Redis 测试覆盖进程重建后的嵌套审批、旧格式审批、原生并行节点部分失败、生产委派产物复用、DAG 与草稿审批、修改后二次审批、拒绝不保存以及夹具键完整删除。合成长状态对照报告在 `logs/checkpoint-storage-comparison.json`，分别统计完整快照和整次运行各类键的内存；不代表线上平均占用。
