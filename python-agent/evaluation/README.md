# Agent / RAG 评测

这套评测用于得到能复核的简历指标，不用单元测试通过率替代模型准确率。真实调用为显式 CLI 操作，离线测试不会访问模型、数据库或 ES。

## 指标与口径

### 完整任务评测（含审批与保存）

新增 `evaluation.e2e`，通过本地 Java API 执行整个 Agent 图，覆盖回答、检索、对比、子代理委派、草稿批准保存和拒绝。会创建独立测试账号；默认清理会话、未发布草稿、检查点及记忆。仅允许回环地址，不使用现有用户。

```powershell
.\.venv\Scripts\python.exe -m evaluation.e2e live --allow-writes --repeats 3 --output ../logs/evaluation/e2e-run1
.\.venv\Scripts\python.exe -m evaluation.e2e score --output ../logs/evaluation/e2e-run1 --reviews ../logs/evaluation/e2e-run1/reviews.completed.jsonl
```

输出 `predictions.jsonl`、`summary.json`、`report.md` 和 `reviews.template.jsonl`。模板里的 `task_completed`、`supported_claims`、`total_claims` 需要人工检查答案及引用正文后填写，**自动契约通过率不能当成事实准确率或引用支持率**。完整调用耗时包含生成和审批恢复，脚本立即审批，不包含用户等待时间。审批阶段的 Token 累计到同一次 run；漏采的 usage 标为未知，不填零。失败、超时和未完成样本保留在分母里。

使用 `--keep-fixture` 保留仅用于界面验证的测试账号，验证后用 `cleanup --allow-writes --output <同一输出目录>` 清理。fixture.json 仅保存在被忽略的本地报告目录，不应上传（其中包含临时账号凭据）。报告中的 LLM 次数按 LangChain 调用统计，不等同于 SDK 内部 HTTP 请求数。

| 对象 | 指标 | 说明 |
| --- | --- | --- |
| 平台检索 | Hit@1/3/5 | 前 K 篇是否包含至少一篇人工标注的相关文档；不能称为答案准确率 |
| 平台检索 | Recall@K / Precision@K | 命中相关文档数 / 全部标注相关文档数，或 / K；同一文章多个块只计一次 |
| 排序 | MRR@K / nDCG@K | 首篇相关结果位置，以及0–3人工等级的排序质量 |
| Main 首次决策 | 路由准确率 | answer/retrieve/delegate/write_draft；retrieve 检查 knowledge/memory 及标签指定的 allow_web。复杂题允许多个合理动作 |
| 耗时 | 平均、P50、P95 | 成功样本及所有已记录请求分别报告，计时包含网络等待；不含预热、不等于首 Token 或完整任务端到端耗时 |
| 调用与用量 | LLM、Embedding、Rerank 次数；输入/输出 Token | 应用层调用次数；Chat SDK 禁止自动重试，未知 Token 不填零；未采集 Embedding Token 和费用 |
| 人工回答复核 | 事实准确率、证据支持率、任务完成率 | correct_claims / total_claims、supported_claims / total_claims、完成任务数 / 已评审任务数；人工与 LLM 评审分开，不自动从“有引用”推出“回答正确” |

百分比的分母包含标注样本的失败、超时、缺失试验；这些检索/路由试验得0分。输出请求成功率、缺失数、错误数及降级次数，不能只留下成功结果。P95 使用线性插值；小样本时它不代表稳定的生产长尾，正式报告建议至少30个不同问题、每个重复3次，并注明问题数与试验数。

## 扩展多轮端到端评测

`datasets/e2e.scenarios.jsonl` 包含 **136 个预先编写的合成场景、183 轮用户提问、26 次计划审批/修改恢复请求**，覆盖13类：直接回答、平台检索、多轮追问、跨会话记忆、草稿审批修改、依赖委派、歧义澄清、无结果、安全、文章关联、联网、SSE、长输入。安全题中的审批是可选分支，实际请求数和模型调用数以报告为准。数据不使用真实用户日志，也不等同于独立人工标注的真实问题。

默认不选择4条联网题，因此计划为132个场景、179轮提问；使用 `--include-web` 才把联网题纳入分母。`--limit` 按类别轮流抽样，而非截取文件前N条。类别可以用 `--categories memory draft stream` 选择。文章标签沿用24篇固定合成语料，运行前核验文章归属、公开状态和内容hash；语料缺失时直接停止，不能用空索引凑结果。

```powershell
# 在python-agent目录；只生成/校验静态数据，不调用模型
.\.venv\Scripts\python.exe -m evaluation.scenario_data
.\.venv\Scripts\python.exe -m evaluation.scenarios validate --include-web

# 首先抽样验证各类别；输出必须是新目录
.\.venv\Scripts\python.exe -u -m evaluation.scenarios live --allow-writes --limit 12 --output ../logs/evaluation/scenarios-pilot

# 全量，单场景总时限240秒；并发默认1，便于与串行测试比较
.\.venv\Scripts\python.exe -u -m evaluation.scenarios live --allow-writes --include-web --repeats 3 --output ../logs/evaluation/scenarios-full

# 可另外做并发2或4的测试，结果应与串行测试分别报告
.\.venv\Scripts\python.exe -u -m evaluation.scenarios live --allow-writes --concurrency 2 --output ../logs/evaluation/scenarios-concurrent

# 人工填写模板副本后评分，不改原始预测
.\.venv\Scripts\python.exe -m evaluation.scenarios score --output ../logs/evaluation/scenarios-full --reviews ../logs/evaluation/scenarios-full/reviews.completed.jsonl

# 中断续跑：选集、seed、并发、重复次数及数据hash必须与原计划一致
.\.venv\Scripts\python.exe -u -m evaluation.scenarios live --allow-writes --include-web --repeats 3 --continue-run --output ../logs/evaluation/scenarios-full

# 清理失败或保留界面测试数据时，按已保存的账号清单继续清理
.\.venv\Scripts\python.exe -m evaluation.scenarios cleanup --allow-writes --output ../logs/evaluation/scenarios-full
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_e2e*.py' -v
```

每个场景拥有独立临时账号，避免画像和记忆污染后续题；同一场景的追问保留会话，只有标记的跨会话步骤新建会话。清理仅操作带专用账号标记的账号和其未发布草稿；若发现已发布文章则停止该账号清理并记录，不会扩大删除范围。

输出冻结的 `cases.frozen.jsonl`、原始逐轮 `predictions.jsonl`、`failures.jsonl`、类别汇总、报告和人工评审模板。每轮保存答案、引用、文章来源版本、执行节点、前后画像/记忆和草稿数据库状态。多次审批只累计每个run最新的Token快照，不重复计数。失败、超时、中断缺失均留在计划分母，重跑失败需要新实验目录，续跑仅补未记录样本。

草稿测试覆盖修改后重新暂停、新hash、旧审批失效、批准前无保存、批准后未发布、拒绝无保存。旧审批同时检查409冲突状态、账本仍在等待审批、没有误保存；只有错误码不符时继续完成合法审批并记录失败，业务状态被改变时停止后续动作。记忆第9条场景在同会话进行6轮普通问答，并断言没有生成历史事件提取任务；最后跨会话要求查询历史事件，应如实说明没有记录。该用例用于验证旧机制已退役，不能把普通问答保存成长期记忆。旧实验目录保留原始数据，不能用于代表当前实现。真实SSE检查事件分帧、序号、完整结束和账本答案一致性。另有MockTransport超时与流中断测试，**这些模拟故障检查不能写成线上真实故障恢复通过率**。

场景P50/P95是整个用户旅程，单轮P50/P95是一次提问连同其审批修改的完整执行；账号准备/清理不计入耗时。首事件时间不等于首答案时间，首答案也不等于原始模型首Token。并发不同、场景长度不同的耗时不可直接拿来宣称性能提升。

自动契约包括引用ID有效、标注相关文章被使用、来源版本有效和保存状态，不自动评判每个事实。歧义是否澄清、拒答是否正确、无结果是否如实说明、记忆是否被遵循及修改内容是否正确，按每条 `review_rubric` 独立人工复核。未评审不填准确率。当前数据仍未覆盖真实图片理解、96K压缩、服务重启或真实工具故障注入。

`--fail-on-contract` 可用于CI，使失败/缺失返回非零但保留完整报告。本地HTTP请求禁用环境代理，始终只调用固定loopback地址；不会将评测凭据发送到远端。`fixtures.json`只含临时账号标识，保存在忽略的logs目录。

## 准备数据

`datasets/route.jsonl` 有16条根据当前产品规则编写的初始路由用例，是冒烟集，不代表真实用户分布。建议补充真实问法、长上下文、歧义、用户约束和复杂任务，冻结标签后再跑，避免看到输出后改答案。

`datasets/route.expanded.jsonl` 是144条扩展用例：保留16条原始冒烟题，加上泛化表达、检索范围、历史记忆、草稿流程、复杂任务、歧义、上下文约束、安全行为八组，每组16题。通过 `python -m evaluation.expanded_routes` 可重建相同标签。标签为执行前按产品规则编写，`reviewed=true` 表示标签已冻结且通过格式校验，**不表示独立真人评审**。安全题包含越权、秘密泄露、伪造引用、提示注入及合法安全教育，测试只调用首次模型决策，不执行返回的工具或记忆变更。

复杂题允许检索或合理委派；它们不用于强制提高子代理调用率。歧义、上下文和安全等64题设置 `requires_behavior_review=true`，每题3次时共有192次语义复核需求。路由得分不能替代拒答正确率、澄清质量或上下文遵循率。报告按类别汇总并列出每次不匹配；未经复核不填安全通过率。该扩展集仍是模型编写的受控产品规则样例，后续须补充独立真实问法、长上下文及完整任务评测。

```powershell
.\.venv\Scripts\python.exe -m evaluation.expanded_routes
.\.venv\Scripts\python.exe -u -m evaluation.run live-route --cases evaluation/datasets/route.expanded.jsonl --repeats 3 --warmup 1 --output ../logs/evaluation/route-expanded-run1
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_expanded_routes.py' -v
```

扩展路由输出保存完整 `decision`、`reply`、`allow_web`，并导出 `behavior-review.jsonl` 复核清单。审阅者逐条检查 `expected_behavior`，将 `behavior_review={"assessor":"human","passed":true或false}` 写回对应 case_id/variant/repetition 的原始 predictions 记录副本，再运行 score。LLM辅助复核使用 `assessor=llm`，与人工分开统计；通过率仅以已复核记录为分母，同时报告待复核数。只审阅首轮回复/决策，后续审批保存、权限拦截和DAG执行仍需端到端测试。

`datasets/rag.template.jsonl` 有12条待标注检索问题。根据当前博客实际覆盖的内容调整、扩展到30–50题，覆盖概念、同义表达、代码、比较、分类/作者条件。人工检查相关公开文章，填入真实 article_id 与相关性等级，然后设置 `reviewed=true`。例如下列仅为格式示例，不是项目真实标注：

```json
{"id":"rag_01","kind":"rag","query":"如何融合检索结果？","reviewed":true,"relevance":{"42":3,"85":1}}
```

不要只把某个检索器返回的前5篇当成所有相关文档，否则 Recall 会偏向该检索器。可合并四种方案的候选池，人工逐篇判断，并补充已知但漏召回的文章。没有任何相关文档的拒答题另行评估；当前检索相关性评分要求至少一篇正例。索引重建后应重新确认标签；每次报告保存样本文件和源码 Hash。

## 真实执行

### 已补充的合成样例

`datasets/rag.samples.articles.jsonl` 包含24篇合成技术文章，`datasets/rag.samples.cases.jsonl` 包含48道问题及预先冻结的相关文章等级（0–3）。每篇文章配术语题和场景改述题，并保留标注依据。标签来源为 `synthetic_authored`；此处 `reviewed=true` 表示样例标签已做一致性校验，**不表示真人独立评审**。标签在检索前生成，不根据某个检索器的输出修改。

本地导入使用独立“RAG评测样例”作者，调用真实文章发布接口，走现有 HTML 分块、Embedding 和 RabbitMQ 索引流程。评测题按作者过滤，确保只比较这24篇固定文章。原账号文章计数不因样例增加。样例会显示在本地平台公开文章列表中，标题统一带 `[评测样例]`。

```powershell
# 生成静态文章与标签（不访问模型、数据库）
.\.venv\Scripts\python.exe -m evaluation.sample_data
# 导入本地服务并等待索引就绪；重复导入复用已有文章，拒绝覆盖被修改的样例
.\.venv\Scripts\python.exe -m evaluation.local_samples seed
# 上一步把样例文档ID绑定成真实article_id，文件写到本地logs目录
.\.venv\Scripts\python.exe -m evaluation.run live-rag --cases ../logs/evaluation/sample-corpus-v1/cases.jsonl --repeats 3 --warmup 1 --output ../logs/evaluation/rag-samples-run1
# 删除清单内的原样文章；若文章已被修改则停止，不覆盖人工编辑
.\.venv\Scripts\python.exe -m evaluation.local_samples cleanup
```

这套数据可以验证检索链路、初步比较四种方案，但文章与问题均由模型编写，可能有简单化和标签偏差。结果须注明“24篇合成文章、48条合成问题”，不能作为真实查询的人工标注准确率。后续保留另一批独立真实问题和人工标签用于最终验证。

在 `python-agent` 目录运行，沿用项目配置。live-route 需要真实 LLM；live-rag 需要 MySQL、ES、Embedding（rrf_rerank 还使用配置的 Reranker）。Java 需已完成 `html-dom-v1` 公开文章重建，不能用空索引测效果。

```powershell
# 只调用首次结构化 Main 决策，不执行其动作，不保存草稿或记忆。
.\.venv\Scripts\python.exe -m evaluation.run live-route --cases evaluation/datasets/route.jsonl --repeats 3 --warmup 1 --output evaluation/results/route-run1

# 标注后复制为 rag.labelled.jsonl。四方案同一原始问题、同一块索引、同一元数据过滤。
.\.venv\Scripts\python.exe -m evaluation.run live-rag --cases evaluation/datasets/rag.labelled.jsonl --repeats 3 --warmup 1 --output evaluation/results/rag-run1

# 可选：另测包含真实 Query Rewrite 的流水线。每次保存展开查询以便审查。
.\.venv\Scripts\python.exe -m evaluation.run live-rag --cases evaluation/datasets/rag.labelled.jsonl --rewrite --repeats 3 --output evaluation/results/rag-rewrite-run1
```

默认检索对照为 bm25、knn、rrf、rrf_rerank；都是当前同粒度索引的消融对照，**不是旧版本性能对照**。默认不调用 Query Rewrite，确保各方案原始查询一致；开启 `--rewrite` 后模型扩展可能不同，不能将差异全部归因于 RRF。所有模式禁用联网、仅处理公开文章，均不做索引写入。查询、原始结果ID和报告会保存在本地，测试集不要填入真实隐私或密钥。

每个真实样本默认最长180秒，SDK Chat重试次数为0；顺序随机且固定seed=42，默认每种方案预热1次。记录 rewrite/rerank 降级状态，分辨服务失效时的回退结果。温度0仍不保证云端模型完全确定。RAG计时包含筛选条件解析、ES/Embedding、MySQL版本核验和可选精排；不含答案生成、Java转发和前端传输。

运行时记录模型、向量维度、依赖版本、源码和样本Hash、操作系统，以及公开文章数和当前版本块数（读取失败记为null）。当前串行测量、并发为1，不是吞吐量/QPS压测。比较期间应冻结文章和索引内容，并在最终报告补充服务器硬件、网络部署方式，避免将数据变化误认为算法效果。

输出目录包含逐条 `predictions.jsonl`、汇总 `summary.json`、可读 `report.md`。已有原始输出的目录会拒绝覆盖。异常时保留已经完成的记录，缺失试验在后续 score 中计零分。启动/预热失败且没有记录时，报告没有质量指标，不会生成虚假的0%或100%。

## 回答与完整任务评审

live-route 在 answer 动作中会生成首轮回复，live-rag 不生成答案；两者均不执行完整 Agent 工作流，所以默认没有回答准确率、引用支持率、任务完成率。要测这些指标，需要从真实任务记录采集答案、证据和任务要求，由另一位评审者逐项标注，例如向记录加入：

```json
{"answer_review":{"assessor":"human","total_claims":4,"correct_claims":3,"supported_claims":2,"task_success":false}}
```

分别定义事实是否正确、是否得到所引资料支持、是否完成用户要求；草稿任务还应检查审批与实际保存，不能仅靠 status=ok 判断。LLM评审只能作为辅助，填写 assessor=llm，报告与human分开。上面的计数仅为格式示例。

```powershell
.\.venv\Scripts\python.exe -m evaluation.run score --cases evaluation/datasets/rag.labelled.jsonl --predictions evaluation/results/rag-run1/predictions.jsonl --repeats 3 --output evaluation/results/rag-scored
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_evaluation.py' -v
```

## 简历填数示例（占位，必须替换成实际报告）

- 在 N 条人工标注问题上对比 BM25、KNN 和 RRF+Reranker，Hit@5 从 A% 提升至 B%，MRR@5 从 C 提升至 D；成功检索流水线 P95 为 T 秒。
- 基于 N 条路由用例、每题重复3次，Main 首次动作/检索目标准确率为 A%，首轮决策 P50/P95 为 X/Y 秒。
- 对 N 个真实任务进行独立人工评审，任务完成率为 A%，事实准确率为 B%，引用证据支持率为 C%。

比例的变化明确写“百分点”或“相对提升”；耗时改善须注明同模型、同硬件、相同数据及负载。不能把配置上限、测试框架的假数据分数或单元测试通过率当成用户任务效果。


## 运维与索引恢复回归（2026-10-06）

`../scripts/maintenance-check.py` 使用临时管理员、作者、文章和 ES 文档，真实验证后台访问权限、参数边界、任务元数据脱敏、失败重试审计、阅读量单调同步，以及孤儿正文/分块删除。默认自动清理临时数据；`--preview` 仅用于界面检查，按 Enter 清理。所有模型和 Embedding 调用均为 0，不生成新的回答准确率或线上恢复率。

离线边界测试见 `tests/test_index_reconciliation.py`，包括版本重查、当前数据优先、过期租约不能提交、达到重试上限后不自动重置、分块序号/总数校验和清理保留审批记录。Java 运行管理与推荐多样性测试随 `mvn test` 运行；前端测试随 `npm test` 运行。GitHub Actions 将三套离线检查及前端构建串入独立任务；数据库和模型评测保留为显式本地操作。
