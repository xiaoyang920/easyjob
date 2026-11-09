# Agent 运行与质量优化（2026-10-04）

## 记忆重复与冲突

常见约束使用固定身份：article_audience、response_language、response_detail、web_search。后端将 audience、target_audience、reader_level 等已知别名统一为同类字段，并识别已有数据库中的旧别名。不批量改写用户历史数据。少量明确同义值（如“新手”“初学者”）归一为“面向初学者”，不对自由文本做模糊合并。

相同范围、同类约束和相同值再次提交时返回 unchanged，不新增记录或向量。已有不同内容而未引用旧记录时，事务回滚并返回确认提示；不会继续执行原拟检索或写作动作。明确替换引用旧 id 时停用旧记录并创建新记录。已有多条冲突旧别名要求先在记忆管理页整理。管理 API 也检查别名冲突，不能通过重新启用旧记录绕过。

决策仅对同用户、同作用范围、相同正文去重，使用二进制比较避免大小写及数据库排序规则造成误合并；不同表述但语义相似的决策不会自动合并。仍由 Main 判断哪些是用户明确确认的决策，普通问答、引用和假设不应写入。画像并发冲突改为明确提示，避免覆盖另一会话的新值。

## 检索降级

此前已有独立 EvidenceSelector 校验，并非粗排结果直接作为证据。本次补齐 platform.rerank 状态到 retrieval_report、Main 上下文及流式活动的传递；对精排返回的越界索引、重复索引、布尔/NaN/无穷/非数值或范围外分数、缺失响应结构按故障降级处理。

粗排候选仍必须通过独立相关性核验。核验失败返回 tool_error 且不交付引用；无相关内容返回 insufficient_evidence；核验后有用的降级候选可继续使用，同时保留降级及 partial/sufficient 状态，不能宣称精排成功。

## 生命周期

后台每 60 秒分批检查到期运行，遵循会话行→已有运行行的锁顺序，在锁内重新判断状态、期限和草稿提交情况。未提交草稿的过期运行和过期审批转为 expired，释放活跃运行占位并阻止旧执行者继续写入。已提交草稿保留对账路径。

已终止运行的 Checkpoint 默认保留 30 天，可通过 AGENT_CHECKPOINT_RETENTION_DAYS 配置（最少 7 天）。每小时分批生成幂等清理任务，消费时再次核验可信 owner、conversation、终止状态和保留期，通过 RedisSaver 的线程删除接口清理。正在运行或等待审批的线程不会清理。保留会话、业务运行账本和文章，不增加数据库结构迁移。

## 可观测性

扩展现有受认证保护的 /internal/metrics。增加最近 24 小时的有界持久化样本（最多 2000 个运行、10000 条完成事件），输出各阶段 P50/P95、异常次数、精排降级次数与比例、审批冲突次数、已计量输入/输出 Token、模型调用及已观察到的失败。

新增检索阶段事件：查询改写、粗召回、精排、联网搜索、证据核验；阶段时长不含用户审批等待。模型失败率在旧记录缺少失败计数时返回 null，样本截断、计量不完整和缺失运行指标均可识别；不能将该有界样本当成全站所有请求的完整失败率。指标不返回提示词、聊天正文、资料正文或密钥，不提供未经定价确认的费用估算。

## 验证

- Python 单元回归 352 项通过，包含 SQL 参数绑定检查、约束别名、冲突停止执行、去重、异常精排分数、Checkpoint 保护和有界指标。
- 真实模型记忆回归 10 个原场景 / 28 轮、新增 6 个边界场景 / 13 轮，均通过自动检查。新增场景单独存放于 memory.edges.jsonl，不改变历史冻结评测计划。检查活跃记忆数量、普通问答不变更记忆、跨会话偏好和引用/假设不保存；不声称覆盖所有自然语言表达。
- 真实 MySQL/Redis 专项 14 项通过，覆盖旧字段与同义值重复、冲突回滚、明确替换、决策精确去重、到期运行拦截、真实 Checkpoint 删除、待审批保护及指标读取。临时账号及 Checkpoint 已清理。
- 实际 SQL/ES、查询改写和相关性模型的检索降级专项 4 项通过：相关粗排资料保留、无关候选排除、核验超时不交付引用、异常分数降级。精排和核验故障为注入故障，非第三方服务实际故障统计；本专项不修改公开文章。

首轮真实数据库检查发现多余的 SQL 绑定参数，已修正并增加严格绑定回归；首轮检索专项误将样例语料未包含的 RDB/AOF 问题设为正例，改用原有标注的缓存击穿问题，未将正确拒绝无关资料改成成功。首轮失败报告保留，修复后的结果存于 v2 目录。

报告：logs/evaluation/memory-regression-20261004-v2/summary.json、logs/evaluation/memory-edges-20261004-v2/summary.json、logs/optimization-20261004-storage-final.txt、logs/optimization-20261004-retrieval-v2.txt、logs/optimization-20261004-unit.txt。

复现：仓库根目录运行 python-agent/.venv/Scripts/python.exe scripts/optimization-check.py 和 scripts/retrieval-degradation-check.py；在 python-agent 目录运行 python -m evaluation.scenarios live --cases evaluation/datasets/memory.edges.jsonl --concurrency 2 --allow-writes --fail-on-contract --output <新目录>。模型专项需要有效模型配置和本地运行服务，会产生模型调用。
