# 结果按需读取改造与真实验收（2026-10-25）

## 实际行为

完整结果仍在 AgentState.task_results。普通回读读取当前执行状态，不额外查询 Checkpointer；来源权限和版本检查仍会按需访问业务服务。LangGraph 的正常检查点写入及中断后的状态还原继续由 Redis Checkpointer 负责。

Main 对较早的大结果只显示目录，默认小结果门槛 8K Token、结果软预算 32K。实际刚完成的结果和最近主动读取的片段优先载入，当前结果允许在完整请求预算内扩展。取消“只因有空余就把全部旧结果重新带入”。总量、压缩、完整历史轮次、字符限制和私有必要输入保护继续生效。

read_task_result 新增字面关键词和引用定位，保留旧字符范围参数。read_task_results 一次最多读取 4 份，整批共享 24000 字符和 WORKER_OUTPUT_MAX_TOKENS/2 的正文预算，每项先校验权限／版本。定位没有命中时明确返回 matched=false，不给空内容附上可用引用。

回读结果记录原始来源、版本、字段及精确范围。模型视图减去重叠片段，存储结果不变；回读的回读解析回原始来源，检查循环、版本及每一跳权限。旧参数及旧 envelope 安全兼容。Main 回答记录实际可见的来源范围；交付核验不能使用未读尾部的 canonical 全文来支持该回答。

## 离线回归

- 全量 1009 项，跳过 9 项，其余通过；没有网络调用尝试。日志：temp/context-access-offline.log。
- 后续补充稳定版本摘要及旧 Checkpoint 新增可空参数兼容后，相关 122 项再次通过。日志：temp/context-access-final-targeted.log。
- 范围包括尾部定位、批量共享预算、非法批次不部分返回、联网限制、私有来源、回读别名、精确重叠范围、原始结果不变、未读证据拒绝、压缩与硬预算、旧任务恢复。

## 真实模型对照

报告：temp/context-access-live-20261025-1/report.json。24/24 通过；4 类场景、3 种策略、每种两次，第二次反转策略执行顺序。调用真实 Main 和核验模型；已有资料为合成日志。这里没有 HTTP 或 Redis 恢复，不能用该报告代替后面的验证。

下表是两个样本的算术平均；输入 Token 为供应商实际统计，调用数包含 Main 和核验。

| 场景 | 策略 | 模型调用 | 输入 Token | 耗时 |
| --- | --- | ---: | ---: | ---: |
| 新的小结果 | 原自适应 | 2 | 18261 | 3.487 秒 |
| 新的小结果 | 固定 32K | 2 | 18261 | 3.104 秒 |
| 新的小结果 | 新按需方案 | 2 | 18261 | 3.333 秒 |
| 旧长结果定位 | 原自适应 | 2 | 93398 | 4.338 秒 |
| 旧长结果定位 | 固定 32K | 3 | 93610 | 6.624 秒 |
| 旧长结果定位 | 新按需方案 | 3 | 39194 | 5.040 秒 |
| 两份旧长结果比较 | 原自适应 | 2 | 113796 | 4.887 秒 |
| 两份旧长结果比较 | 固定 32K | 3 | 116754 | 6.780 秒 |
| 两份旧长结果比较 | 新按需方案 | 3 | 44797 | 5.838 秒 |
| 刚取得的完整长结果 | 原自适应 | 2 | 56982 | 4.334 秒 |
| 刚取得的完整长结果 | 固定 32K | 2 | 56982 | 3.578 秒 |
| 刚取得的完整长结果 | 新按需方案 | 2 | 56982 | 3.372 秒 |

新方案的旧结果定位及多结果比较均只调用一次回读；两个直接载入场景没有新增读取调用。相对原自适应，两个旧资料场景输入分别减少约 58% 和 61%，但额外一次模型决策使平均耗时增加约 0.7 和 1.0 秒。相对固定 32K 方案，本次样本读取更省且更快。小样本包含模型延迟波动，不作延迟 SLA。

三组对照使用同一当前实现及读取接口，通过策略开关切换，不是完整旧版本二进制。新旧接口 Schema、Main 提示及核验行为并非被冻结为历史版本，因此不能把这份结果宣传成整个系统的旧版／新版性能对比。

## 真实 Redis 跨进程恢复

报告目录：temp/result-checkpoint-live-20261025-2，seed.json 与 resume.json。

第一个 Python 进程使用实际 LatestRunRedisSaver 保存完整状态，停在 execute_tool 前；该进程结束后，第二个进程重新创建图及 Saver，从 Redis 恢复。恢复后的批量读取取得长日志尾部口令及第二份结果，完整原文不变，读取范围元数据再次持久化。工具执行期间没有增加 Checkpointer 读取。测试线程已精确删除。

这是无模型的隔离图组件恢复测试，未创建业务运行。第一次尝试因本机 Docker 引擎停止、两个 Redis 不可用而失败；恢复本机依赖后重新用独立目录运行。不能拿 Python /health 存活当成 Redis 已就绪。

## 网站恢复与真实读取

报告：temp/context-access-http-20261025-1/report.json。6/6 通过，测试数据清理成功。

前 5 项通过网站 3000 -> 网关 8090 -> Java 8080 -> Agent RPC -> 模型执行，检查要求建立、撤销和三次 JSON 回忆、MySQL 运行账本、Redis Checkpoint 及历史逐条读回。

第 6 项使用独立测试账号，在真实业务运行和 Redis 中构造待恢复的合成日志检查点，再标记该运行失败；通过网站 POST /api/agent/runs/{runId}/recover 调用生产恢复链路。后台重新授予执行代次，恢复同一个运行，Main 对旧大结果执行一次定位回读后准确回答。实际耗时 7.217 秒；检查运行成功、代次变化、模型供应商用量、原始结果逐字不变和新增读取元数据保存。运行 ID：ff7cb35e-68dd-403f-aef8-2ccfc7b559b8。

该项证明业务恢复接口能够还原真实 Redis 中的任务结果并执行新读取逻辑。中断状态是受控构造，不能把它描述成在任意崩溃点都已故障注入验证。长对话压缩恢复、写作审批恢复及大并发不在本次新增验收范围内。

## 复现与回退

```powershell
$env:PYTHONPATH='python-agent'
$env:PYTHONUTF8='1'
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_live --phase access --output temp/access-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.result_checkpoint_live --phase seed --output temp/checkpoint-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.result_checkpoint_live --phase resume --output temp/checkpoint-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_http_live --result-recovery --output temp/http-access-new
```

输出目录必须尚不存在，resume 使用 seed 的同一个目录。模型对照会调用真实供应商；网站测试创建并清理专用账号。关闭 AGENT_CONTEXT_RESULT_ACCESS_ENABLED 并重启可恢复原自适应策略，不删除结果；关闭 AGENT_CONTEXT_TOOL_ADAPTIVE_INLINE 可再退回固定 32K 投影。回退策略不会移除新增可选读取接口。
