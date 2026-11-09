# 完整请求预算与历史压缩

Main根据完整渲染请求的Token决定是否值得压缩早期历史。读取会话、追加用户消息、保存助手回答不再按历史32K主动调用摘要模型。会话读取提供旧摘要及游标之后按完整轮次分页载入的历史，默认载入软预算为192K；未载入的旧范围明确标记，可以按需回查。原始消息始终保留在MySQL。

## 默认配置

| 配置 | 默认值 | 用途 |
|---|---:|---|
| AGENT_MAIN_CONTEXT_MAX_TOKENS | 262144 | 单次请求的输入、输出预留和安全余量总预算（256K） |
| AGENT_MAIN_OUTPUT_MAX_TOKENS | 8192 | Main输出预留及max_tokens |
| AGENT_WORKER_OUTPUT_MAX_TOKENS | 16384 | 分析、写作输出预留及max_tokens |
| AGENT_CONTEXT_SAFETY_TOKENS | 8192 | 本地估算与供应商封装余量 |
| AGENT_CONTEXT_COMPACT_TRIGGER_TOKENS | 196608 | 完整Main输入192K软触发阈值 |
| AGENT_CONTEXT_COMPACT_TARGET_TOKENS | 65536 | 压缩后的完整输入64K目标（总量的1/4），非硬要求 |
| AGENT_CONTEXT_COMPACT_MIN_SAVING_TOKENS | 4096 | 通常预估及实际至少回收4K才接受压缩 |
| AGENT_HISTORY_RECENT_TOKENS | 24576 | 压缩发生时的近期完整轮次24K软目标 |
| AGENT_HISTORY_LOAD_MAX_TOKENS | 196608 | 从数据库载入历史的192K软预算，按完整轮次停下 |
| AGENT_ARTICLE_CONTEXT_MAX_TOKENS | 32768 | 会话来源文章的首轮32K读取上限，计入总上下文 |
| AGENT_SUMMARY_MAX_TOKENS | 4096 | 摘要内容上限 |
| AGENT_SUMMARY_INPUT_MAX_TOKENS | 32768 | 单次摘要请求输入上限 |
| AGENT_SUMMARY_MAX_CALLS | 8 | 一次压缩流程最多摘要调用次数 |
| AGENT_SUMMARY_TIMEOUT_SECONDS | 45 | 一次压缩流程总模型等待时限 |
| AGENT_AUXILIARY_HISTORY_MAX_TOKENS | 32768 | 查询改写/旧聊天辅助调用的历史视图额度，不参与Main触发 |

旧AGENT_HISTORY_MAX_TOKENS已退役。Main输入硬预算为262144−8192−8192=245760（240K），Worker为237568（232K）。统计包含系统提示词、当前问题、历史、独立摘要、画像、约束、任务结果视图、执行记录和实际结构化输出/工具Schema。单次运行累计调用预算另由AGENT_RUN_TOTAL_TOKEN_BUDGET控制，与单次上下文窗口不同。

本地cl100k_base估算不是DeepSeek精确分词或计费量；应根据实际usage校准。上述阈值是起点，不代表已经测得最优配置。

## 一次Main决策前的处理

1. 渲染完整Main输入并计数。低于192K直接继续，历史超过32K不单独触发摘要。
2. 检查本轮状态context_compaction.attempted_versions；同一运行内同版本历史不重复尝试，任务资料变化不构成新的历史版本。
3. 当前问题、指令和有效约束作为必要输入；任务资料通过受限的模型视图载入，原始结果仍保存在Checkpoint并可按权限回读。必要输入本身超240K时，停止并提示收窄任务。
4. 从历史末尾按完整用户/助手轮次累加，选择约24K的近期原文；根据必要输入和64K目标动态减少保留额度。最新完整轮次始终保留，即使超过24K软目标。
5. 若没有可压缩的早期轮次，或按最大4K新摘要预估不能回收至少4K，就跳过摘要。为解决超过硬预算的请求，可以接受较小但足以回收的收益。
6. 每个决策轮最多执行一次压缩流程；流程内允许受8次/45秒限制的分批摘要，禁止while超过192K就反复调用摘要。
7. 重新计算完整请求，实际收益不足不替换历史、不保存摘要、不推进游标。成功摘要后也记录新版本，下一决策轮不会再次压同一快照。
8. 压缩后仍超过192K但在240K内可以继续；若仍超过240K，明确停止，不反复摘要、不静默截断历史或资料。格式重试和引用修正再次检查硬预算，不再触发第二次压缩。

24K只是在发生压缩时的近期原文保留目标，之后的新对话可以继续累积。64K是整次输入的压缩目标（总量的1/4）而不是固定结果；必要资料较少时压缩后可能远低于64K，必要资料较多或最新轮次很长时可能高于64K。文章32K上限是另一项资料范围额度，不是压缩触发点。

## 持久化与一致性

Main使用请求启动时、当前问题入库之前加载的历史快照。摘要只读取选中的完整早期轮次，不重新把本轮刚入库的问题读入压缩范围。近期原文保留message_id，summary_upto_msg_id只推进到已完整总结的轮次末尾；超长旧轮次可以分段，只有全段成功才能推进。

保存前检查旧摘要及旧游标，并使用MySQL比较条件更新；运行执行权失效或并发过期结果不写入。无收益、空摘要、失败、超时均不虚报完成。原始消息不删除。运行State同时更新history_messages和context_compaction，在后续Main轮次以及checkpoint恢复中沿用。

Redis使用带载入预算的py_ctx:window:v5缓存键，调整历史预算后不复用旧的小窗口。成功持久化摘要和新增消息都会使缓存失效；既有摘要及游标继续使用，无需新增数据库字段。

## 其他边界

| 配置 | 默认字符数 | 用途 |
|---|---:|---|
| AGENT_MAIN_CONTEXT_MAX_CHARS | 1048576 | 完整请求的额外保护 |
| AGENT_MAIN_OUTPUT_MAX_CHARS | 65536 | Main回答、产物、引用修正Schema |
| AGENT_TASK_RESULT_MAX_CHARS | 131072 | 单任务完整结果 |
| AGENT_DEPENDENCY_MAX_CHARS | 524288 | 聚合依赖JSON |

上述字符限制补充Token预算。检索结果按输入额度检查，生成的分析/写作按输出额度检查；依赖及完整Worker请求仍检查各自Token预算。任务资料不会被历史摘要模型概括或改写。查询改写等辅助调用可以选择较小历史视图，并带省略说明，不影响Main完整历史加载。

004_message_content_capacity将ai_message.content扩为MEDIUMTEXT，迁移前需备份。该迁移保留NULL属性、排序规则和注释，可重复执行，已有LONGTEXT不缩小。当前本地已部署；单条用户输入16,000字符及草稿正文100,000字符业务限制继续生效。

## 验证

### 输入框上下文指示

聊天、文章问答和写作侧栏的输入框旁展示上下文圆环。悬停、键盘聚焦或点击可查看占用比例、剩余比例和 Token 数。统计口径是最近一次 Main 模型请求的完整输入估算（含系统提示、历史、工具资料与 Schema），不是本轮全部模型调用的累计计费用量，也不包含输入框中未发送的文字。新会话没有测量时显示“待计算”。

Main 在预算检查通过后发送 `context_usage` 流事件，数字窗口快照随 `metrics.context_views` 保存。刷新时 `/api/agent/conversations/{cid}/context-usage` 校验会话所有权后只查询最后一次数字统计；不读取 Redis Checkpoint、不加载正文、不调用模型。窗口上限来自请求时配置；历史旧统计没有窗口快照时采用当前配置。默认256K，上下文输入硬预算240K（输出和安全余量各8K）。

浏览器仅在切换会话和请求结束时读取接口，生成中通过流事件更新，没有额外轮询。测量值绑定原会话，切换会话时取消旧请求，防止迟到结果覆盖其他会话。

2026-10-29 验证：相关 Python 单元/接口测试31项、前端状态测试19项、模拟接口浏览器测试4项通过。`scripts/context-usage-smoke.py` 经本地3000→网关→Python→MySQL完成6项真实接口检查（未知值、最新统计恢复、数字字段范围、会话权限、重复读取）；临时账号与数据已清理，未调用模型。前端类型检查与生产构建通过。

tests/test_context_budget.py检查渲染、Schema、硬预算、引用和Unicode边界；tests/test_context_compaction.py检查全局触发、历史超过32K不提前压缩、资料占大头时跳过、同版本去重、完整轮次、无收益/失败/超时、分批限次、当前问题保护和游标并发条件。评测入口复用相同准备与渲染逻辑，并记录摘要调用及usage；此前路由报告不能当作本次源码的指标。

```powershell
# 在python-agent目录运行；离线测试不访问外部服务。
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

配置示例见agent-runtime.env.example；修改本地runtime配置后重启Python Agent。
