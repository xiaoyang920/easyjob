# 上下文管理第二阶段实施与验收

实施日期：2026-10-25 至 2026-10-26。对应 [实施计划](38-context-next-optimization-plan.md)。

## 已实施行为

1. 同一 Main 决策共享结果归一化、版本摘要和完整/精简视图；数值 Token 缓存只存在于该次构建，最多 512 项，不保存额外正文。修正后的重试消息仍按实际内容重新计数，业务权限与版本校验不缓存。
2. 现有结果读取工具增加 queries、section_id、cursor。多关键词为字面 OR；章节只索引明确 Markdown 标题，目录最多 32 项。游标绑定原始任务、版本、字段和定位条件，后续命中可继续分页。
3. 批量最多 4 项，仍共享 24000 字符和半个 Worker 输出 Token 预算；空命中、短结果释放预算。完整工具返回的包装、引用、范围元数据也参与输出上限检查。
4. 本轮明确指出已有公开结果及定位词时，首次 Main 决策可预读最多两份、合计 4096 估算 Token 的片段。含糊追问、禁止读取、私有资料、网页、已载入结果跳过。没有明确旧来源时提前跳过准备流程，避免新结果/无关问题的额外视图构建。
5. 预读视图不伪造执行成功的任务；Main 回答、Main 自己生成的分析及对分析的再次读取，均保留实际可见的原始范围。重复依赖按范围去重，防止派生元数据反复增长。
6. RunMetrics 保存估算/实际输入 Token 的对应记录、模型标识、图片数、Schema 数及有界的本地构建计数。缺失或失败用量保持未知，不补 0。校准只观察，不自动改变预算。

完整结果仍保存在 task_results，普通回读不额外访问 Checkpointer；恢复先由 Redis 还原图状态。总窗口 262144、压缩触发点 196608、压缩后目标 65536 保持不变。

配置：

| 配置 | 默认 | 本地部署 |
| --- | --- | --- |
| AGENT_CONTEXT_BUILD_CACHE_ENABLED | true | true |
| AGENT_CONTEXT_RESULT_PREFETCH_ENABLED | false | true，经过下述配对验证后在 .env.runtime.local 启用 |
| Token 估算自动修正 | 未启用 | 未启用，保留安全预留 |

旧读取参数、新增可空参数缺失的旧 Checkpoint 均兼容；新增默认值不改变旧结果读取策略指纹。回退可分别关闭计算复用和预读，不删除结果或检查点。

## 离线验证

- 完整回归 1029 项，跳过 9 项，其余通过；blocked_network_attempts=[]。日志：temp/context-next-full-offline-release-20261026-1.log。
- 后续针对预读准备优化、派生范围去重、已载入片段复用和相关调用链，106 项再通过。日志：temp/context-next-final-coverage-tests.log。
- 预读专项还覆盖了分析产物再次回读不能扩大来源范围、重复依赖不重复扩大元数据、已有可见片段覆盖关键词时不再预读。最后的 106 项包含这些检查。
- 覆盖十处重复关键词完整分页、中文/emoji/CRLF 精确范围、字面匹配、章节边界和代码块、无效/过期游标、批次隔离、预算回收、旧任务指纹、同 ID 新内容不复用旧缓存、缓存条数上限、来源变化及未读证据拒绝。

完整回归在离线进程中关闭默认预读，预读专项在测试内显式开启；真实模型和网站验证另外覆盖启用状态。没有把离线替身当成真实供应商测试。

## 本地准备性能

报告：temp/context-next-cache-final-20261026-1/report.json。三个合成规模，每种开关各 30 次，交错执行。只有组装、计数及准入操作，没有模型或网络。

| 规模参数 | 关闭复用中位数 | 开启复用中位数 | 同一请求 Token |
| --- | ---: | ---: | ---: |
| 2000 | 58.28 ms | 52.07 ms | 23069 |
| 14000 | 82.71 ms | 72.53 ms | 31187 |
| 40000 | 225.90 ms | 188.97 ms | 57184 |

本组本地准备耗时减少约 11%～16%，请求内容和计数保持一致。峰值 tracemalloc 分别约 0.77/1.60/4.28 MB，不是进程总内存，也不证明长期运行无泄漏。原改造前代码已保存到 temp/context-next-baseline-20261025-1/frozen/；上述表格是当前同一实现的开关对照，不是完整历史系统性能对比。最终功能增加了 Schema 和说明，不能把不同阶段的裸 Token 数当成只由缓存引起的差异。

## 真实模型：预读与读取定位

### 预读配对

原报告：temp/context-next-prefetch-live-20261025-1/report.json。4 类场景，每种开关各 10 次，交错顺序；真实 Main 和核验模型，合成资料、内存图，没有 HTTP 或 Redis 持久化。

80 次回答的目标值均正确。开启预读的 40 次全部满足原始检查；原始总检查为 79/80：关闭预读的一次批量样本发生格式修复及第二次读取，超过评测最初规定的“一次读取”，答案仍正确。该失败记录保留，没有重写为全通过。后续评测对基线记录实际次数，不把读取次数上限误当成答案准确性指标。

| 场景 | 开关 | 样本数 | 平均模型调用 | 平均供应商输入 Token | 耗时中位数 |
| --- | --- | ---: | ---: | ---: | ---: |
| 明确单份旧结果 | 关闭 | 10 | 3 | 38789 | 4.901 s |
| 明确单份旧结果 | 开启 | 10 | 2 | 20387 | 3.191 s |
| 明确两份旧结果 | 关闭 | 10 | 3.2 | 46853 | 5.328 s |
| 明确两份旧结果 | 开启 | 10 | 2 | 22084 | 3.254 s |

调用数包含 Main 和核验。明确旧资料的两组中，预读均省去显式读取决策；输入减少约 47% 和 53%。这是受控合成场景的实测，不能推断所有问题都同样提速。

原组新完整结果有约 0.25 秒中位数波动，因此又对“没有明确旧来源时跳过预读准备”做了修改和专门复测：temp/context-next-prefetch-controls-20261026-2/report.json，40/40 通过。

| 控制场景 | 关闭中位数 | 开启中位数 | 两组调用/输入 Token |
| --- | ---: | ---: | --- |
| 刚取得完整结果 | 3.292 s | 3.021 s | 均 2 次 / 54210 |
| 与资料无关的问题 | 2.823 s | 2.764 s | 均 2 次 / 18902 |

这组证明没有新增模型调用或输入正文，不作为供应商延迟 SLA。未用少量样本宣称 P95 改善。

### 模型生成新读取参数

报告：temp/context-next-locators-live-20261026-1/report.json，6/6 通过。模型实际生成 queries、section_id、cursor 参数，而非只直接调用 Python 读取函数。

- 多关键词和章节定位各两次，均取得准确值并使用要求的定位参数。
- 强制按 needle 和 1500 字符窗口寻找第十处命中，各通过四轮读取，完整请求包含 Main/核验共 6 次模型调用，约 14.1/14.4 秒。
- 分页场景用于验证可达性；已知更精确关键词时应直接定位，不能把强制逐页遍历宣传成最快策略。

## Token 校准

报告：temp/context-next-calibration-live-20261025-1/report.json，12/12 真实调用通过。中文、英文、代码、混合文字、Schema、原生图片各两次；图片为程序生成的单色测试图，没有使用用户图片。另有预读对照 182 次调用的估算/实际配对。

| 独立校准分组 | 样本 | 实际/估算中位数 | 最大值 |
| --- | ---: | ---: | ---: |
| 纯文本，无 Schema | 8 | 0.906 | 0.992 |
| 结构化 Schema | 2 | 0.614 | 0.614 |
| 原生图片 | 2 | 0.195 | 0.195 |

预读对照 182 次的实际/估算中位数约 0.914、最大约 0.957。本组估算偏保守，样本尤其是图片与边界规模不足以降低安全余量。因此交付配对指标和离线报告工具，保持观察模式，不自动放宽 256K 准入。

## Redis、网站、长对话和审批

### Redis 分进程读取恢复

- temp/context-next-checkpoint-20261025-1：独立进程恢复完整结果并批量读取，原文不变、范围再次持久化；读取器执行期间未增加 Checkpointer 查询。隔离图组件，无业务账号/模型。
- temp/context-next-checkpoint-stages-20261025-1：在首次读取前、读取完成后、最终组装前分别暂停，Python 进程退出后由另一进程恢复。3/3 通过，后续命中游标和来源范围保留，已完成的读取不重复执行。测试线程已精确删除。

这是受控图暂停，不是任意指令位置的进程崩溃注入。

### 完整网站链路

temp/context-next-http-20261025-1/report.json：网站 3000 → 网关 8090 → Java 8080 → Agent RPC → 模型，6/6 通过，原始历史逐条读回一致，夹具清理成功。

前五项验证有效要求和撤销；第六项构造一个合成中断业务 Checkpoint，再从网站恢复同一运行。恢复后预读命中，不再增加显式读取任务，正文逐字不变、范围元数据保存，耗时 4.498 秒。运行 ID：1f98438f-d925-4348-9f69-7a5bd827bc8f。

最终准备优化与范围集合去重部署后，另一次网站 6/6 验收报告见 temp/context-next-http-final-20261026-2/report.json。最后补充可见范围复用检查后再次部署，并经网站验证同一运行的并发恢复，1/1 通过且清理成功，报告见 temp/context-next-recovery-release-20261026-5/report.json。

### 真实压缩后的跨进程恢复

temp/context-next-long-recovery-20261025-1：第一进程创建独立会话，原请求约 212021 Token，使用生产 ConversationService 和真实摘要模型压缩为约 33449 Token，一次摘要调用，真实写入 MySQL 摘要/游标及业务 Redis Checkpoint。

第一进程退出后，第二进程先检查 Redis 摘要摘要值，再经网站恢复同一个失败运行。结果通过：当前期限为 2026-11-20、项目灯塔-N9、不自动缩进；MySQL 摘要和游标保持一致，恢复耗时 3.107 秒。任务要求夹具通过既有逐字原话校验构造，不能据此单独宣称所有自然语言任务要求都能被模型正确提取。独立账号及其数据已清理。

### 审批与并发

审批证据：temp/context-next-approvals-concurrency-20261026-3/report.json 的两项审批均通过。待审批内容从 Redis 读回，普通恢复接口拒绝自动执行；拒绝不保存，确认只产生一份草稿和一份保存回执，重复确认返回 409 且不增加草稿。检查的是 article_revision 中的本人草稿，不是只存公开投影的 article_info。未将其描述为审批中强制杀进程测试。

并发证据：temp/context-next-concurrency-20261026-4/report.json，4/4 场景通过。

| 请求数 | 各请求耗时 | Agent 进程 RSS 采样最大值 |
| --- | --- | ---: |
| 1 | 3.828 s | 264581120 bytes |
| 2 | 3.284 / 3.284 s | 264986624 bytes |
| 4 | 5.088 / 3.433 / 7.550 / 6.423 s | 265535488 bytes |

这些是同用户不同运行；每用户执行上限仍为 2，四请求包含正常排队。各运行/会话/回答互相隔离。RSS 是确切 Agent 启动器和工作进程的采样和，含共享页，约 253 MiB；不是整个项目占用、长期泄漏证明或容量 SLA。

同一失败运行的两个恢复请求得到 200/409，只授予一个新执行代次，只追加一条助手消息。所有运行使用专用测试身份，清理成功。

## 验收中修正的测试夹具问题

- 第一次跨进程登录试图使用数据库中的旧测试密码；登录已将其迁移为哈希。改为只给确切 evaluation 测试身份轮换临时密码，避免把凭证写入跨进程清单。首次失败日志保留。
- 初次审批计数误查 article_info，已改为 article_revision；一份遗漏的测试草稿按清单用户 ID 和 data_source=evaluation 精确清除，证明见 cleanup-repair.json。
- 把所有审批/重复确认/并发请求放在同一身份一分钟内，触发了现有每分钟 12 次的网关限流。改为分组独立测试身份，保留生产限制。
- 多身份沿用同一测试昵称触发唯一索引；已随机化昵称。失败报告与后续通过报告分别保留。

上述问题没有通过提高线上限流、删业务数据或覆盖失败记录解决。

## 运行与回退

已使用已有空闲运行门禁及 Java→Agent RPC 两次连续探测受控重启。最终日志：logs/context-next-restart-release.log。一次性服务启动任务无触发器，验收结束移除任务注册，服务继续运行。

最后核对：8 个已记录的测试身份，其用户、会话、运行、文章投影及草稿版本均无剩余记录，已知消息和本阶段身份前缀也为零。证明：temp/context-next-cleanup-verification-20261026.json。三个临时启动任务注册已移除：temp/context-next-service-task-cleanup.json。移除后前端、网关、Java、Agent 均返回 200；Agent 的 MySQL、Redis、Checkpoint、Elasticsearch 依赖全部 up。证明：temp/context-next-health-release-20261026.json。

复现需本地依赖就绪，输出目录必须是新目录；seed/resume 使用同一目录并在两个 Python 进程运行：

```powershell
$env:PYTHONPATH='python-agent'
$env:PYTHONUTF8='1'
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_build_perf --output temp/build-new --repeats 30
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_live --phase prefetch --output temp/prefetch-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_locator_live --output temp/locator-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.token_calibration_live --output temp/calibration-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.result_checkpoint_stages_live --phase seed --output temp/stages-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.result_checkpoint_stages_live --phase resume --output temp/stages-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_extended_live --phase seed --output temp/long-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_extended_live --phase resume --output temp/long-new
.\python-agent\.venv\Scripts\python.exe -m evaluation.context_extended_live --phase http --output temp/http-extended-new
```

模型与 HTTP 评测调用真实供应商，创建独立测试身份；请勿对现有业务身份注入故障。内存采样需重新记录当前 Agent 进程 ID，缺少有效 ID 时明确显示不可用。

汇总及生产代码摘要：temp/context-next-acceptance-20261026.json。没有完成长期高并发、任意崩溃点、不同供应商模型或边界图片分辨率的全覆盖；当前结论限于上述明确场景。
