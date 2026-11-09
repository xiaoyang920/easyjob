# 有据交付与执行事实校验

本次增加的是应用自己的交付校验，不是宣称复制 Codex 内部防幻觉实现。

## 正常路径

Main 仍执行决策→执行→观察循环。知识检索后，Main 在同一次决策中选择原始引用、评估 sufficient/partial/none 并确定下一动作；没有恢复独立检索充分性 LLM。

## 综合回答与来源判断

普通概念、比较、方案和排错问题围绕用户目标组织：先回答核心问题，再解释原理、推导、条件和取舍。Main、Analysis 和 Writing 合并多份资料的重复观点，不默认逐来源复述，也不汇报平台/联网命中清单。只有用户明确要求找文章、推荐资源或逐篇总结时使用资料列表。来源支持关键具体事实，稳定常识、原创示例和明确条件的建议不要求逐句引用。

资料覆盖程度不等于可回答程度：检索不相关或不完整时仍可解释稳定通用知识，不能拿通用知识冒充指定文章内容、当前平台状态或精确实时事实。Main 同一次决策结合实际可见的版本、日期、适用条件、全文/摘要及来源关系判断采用哪些资料；优先相关的一手信息。URL、网站标题、排名、精排分数或多个转载不证明权威性/真实性，多个镜像不算独立佐证。

引用真实与原文支持是程序/语义检查的一部分，不是来源正确的证明。核验模型应拒绝把明显算术或逻辑错误、违背可靠稳定知识及来源内部矛盾的说法直接当事实；可以准确转述“该来源声称X”，同时指出X的错误或不确定性。不能凭模型不确定的记忆推翻版本性新事实；无法解决时说明条件和争议。该判断仍由模型执行，不是独立事实认证，也不增加一次“真伪裁判”调用。

分析/建议也检查条件、概念和范围，不能把数据新鲜度容忍度偷换为请求响应时延容忍度，或从仅失败补偿异步推出整个请求不等待。对比表不为填满维度编造条件；示例涉及幂等或状态变更时检查未完成操作被提前记为成功的失败窗口。允许模型推理不代表任何标记为“建议”的断言都自动通过。

## 正文核验

`decision_context.execution_facts` 从当前任务结果、检索报告和记忆写入状态生成，包含平台/联网状态、精排状态、草稿是否保存以及最近失败运行的位置。模型的计划和生成正文不能改变这些状态。`found` 不表示相关或充分，`empty` 不证明整个平台不存在资料。

最终 `final_gate` 先检查引用及站内文章版本，再核验实际正文。没有外部资料、执行矛盾且未判定为证据不足的普通概念解释不增加调用；仅正文无引用不意味着跳过已取得来源的核验。资料型回答通常增加一次结构化核验；发现问题时最多一次局部正文修正，再核验一次，即上限为两次核验＋一次修正。单次默认25秒，核验输出默认4096 Token；遵守整个运行的累计 Token、执行租约和取消边界。

首轮核验发现可通过公共资料补齐的来源事实缺口时，图走 `final_gate → main_agent → execute_tool → final_gate`。Main仅返回一次受控的检索请求或null；不重新生成整篇回答、不委派、不写草稿或记忆。该决策与检索仍占用现有轮数、任务数、重复动作、权限、取消和总运行预算。最多安排一次补检索；无益、重复、超限或检索超时时，利用已有资料修正。个人实测指标、实际配置及未确认的用户条件不自动联网填补；常识、建议及推理错误也不触发此补检索。

候选正文、原问题清单、首次核验的安全内容投影及计数保存在 `delivery_review` Checkpoint；恢复后不重复首次核验。补检索产生新任务和真实来源编号，不覆盖成功结果；新旧原始来源合并并重新检查版本后用于修正，只有最终正文使用的引用对用户展示。只增加最多一次Main检索决策及一次检索，核验仍最多两次、修正一次。当前自动补检索针对普通回答；草稿继续在生成节点内核验，通过后才能进入审批。

修正模型读取完整候选、新旧来源和问题清单，只输出 `replacements[{block_index, issue_block_index, text}]`。后端拒绝重复、越界、漏修问题段或没有真实问题锚点的补丁，按原始文本位置替换问题段及受影响段落；未修改正文保留原始字符、换行和空格。草稿的标题、摘要、正文分别寻址，未修改字段原样保留。依赖段是否需要联动由模型判断，完整修正稿仍需复核，不能将补丁应用成功等同于语义正确。

核验输入包括后端切分的全部实际正文段、原始来源正文、执行事实和本次用户请求。草稿 JSON 先解析，再单独核验标题、摘要和正文；代码块内的空行不拆段。每段按句末、分号、换行及正文引用位置划分单元，后端生成 block_index、unit_index 和来源 evidence_catalog。模型对每个单元返回 kind、verdict、必要的 rationale/reason 和 evidence_ids，不要求重抄正文、代码或来源。后端用编号绑定原文，检查全部段和单元被覆盖，拒绝未知依据编号；全篇上限80段、160条判断，超限不静默截断。单元内有多个结论时，任何一项不成立，整个单元进入修正，reason说明具体问题。旧回放记录的显式 statement/quotes 仍支持严格原文覆盖检查，但新核验提示词不要求输出这些字段。

来源正文只在 evidence_catalog 中传入一次，按最长1200字符分配依据编号（标题及链接另编号）；这些分片仅用于核验，不作为用户回答展示。选择编号不能证明事实真实，语义是否支持仍由核验模型判断。核验输出预算按单元数调整，最低为配置的4096 Token、最高为 worker 输出预算，仍受整个请求预算约束。

## 分类核验

不是每条结论都必须在来源中直接出现。分类与语义判断由同一次核验模型调用完成，不增加独立分类 LLM：

| kind | 核验方式 |
| --- | --- |
| source_fact | 明确归属资料的说法、当前信息、实测指标/版本及平台事实需有真实摘录；有依据但漏标引用由后端补齐，不能虚构或与来源冲突 |
| inference | 检查前提和推理；rationale说明资料、用户条件或显式假设如何导出结论，引用摘录证明前提，不要求原文直接给出最终推论 |
| recommendation | rationale说明理由、适用条件及取舍；不强制每句建议引用。建议包含的独立具体事实仍需拆开核验 |
| general_knowledge | 稳定通用概念不因缺少引用拒绝；不能把具体网页说法、实时版本/指标和项目事实伪装成常识 |
| illustration | 自行编写的示意代码、JSON、教学表格和例子检查合理性及矛盾，不要求来源包含相同例子、函数名或演示数字；声称符合特定API或真实执行结果仍需依据 |
| execution_fact | 以后端执行记录为依据，不要求网页证明；计划或模型正文不证明保存、联网、记忆写入成功 |
| non_factual | 标题、连接词、提问、礼貌或明确的不确定性说明；不应用于跳过事实 |

例如“来源说明重试不保证强一致，因此若业务要求读取立刻反映写入，就不能只依赖重试”中的前提由来源支持，后半段是条件性推导。“若可容忍短暂延迟，我建议先验证简单方案”是方案建议，不要求来源直接推荐同一方案。建议句中的虚假绝对保证仍不能放行。

先按内容性质分类，再核验；做过检索、段落邻近引用或内容位于表格/代码里，不意味着必须归类为来源事实。来源未提及不等于错误，稳定解释、教学示例和合理建议不要求逐句从来源推出。明确声称“原文说/官方要求”的内容仍是来源事实。

引用后缀组绑定上一引用组之后的正文；例如 `结论甲[A]，结论乙[B]` 分别只允许用 A、B 证明，不能用段落引用并集混用。`结论甲。结论乙。[A]` 两个句子共享末尾 A。并列 `[A][B]` 或 `[A] [B]` 绑定同一组，可以由 A、B 支持其中不同事实，不要求每个单元同时使用全部引用。来源事实需要真实支持摘录，且摘录必须来自实际标注的来源集合；常识、示例、建议及非事实片段允许不选摘录，即使邻近或附带背景引用，也不因此删内容。没有使用某个引用不等于结论错误，不再将 unused_citation 作为内容失败条件。真实矛盾、虚构来源说法、缺少事实依据或拿未标注的 B 证明 A，仍进入修正。代码及 Markdown 链接标签中的数字不当引用，数字列表的 `1.` 与后续文字保持同一单元。有真实依据、仅漏标引用的来源事实，由后端补齐引用，不额外调用修正模型、不删内容。标题/摘要无引用时允许核验所选来源，有引用仍强制绑定。

Main 不再因为已检索而要求回答至少出现一个标号；未知标号仍立即进入引用修正。缺少引用是否构成问题交给 final_gate 的分类核验，所选原始资料保留至该门禁结束，因此不会因初始正文没有引用而跳过语义核验。正常路径不增加独立分类调用。

后端同时解析明确的 Markdown 引用范围：`**步骤**[A]：第一步；第二步` 的正文步骤继承 A；`**选型**[A]：`、带引用的 Markdown 标题，以及紧接表格/代码/列表前以冒号结尾的带引用引导句，可约束紧接的一个正文块，遇到新标题停止，不能扩展到整个回答。表格后的 `来源：[A]`、`Source: [A]` 或 `（以上表格内容均来自[A]）` 绑定紧邻的表格/代码/列表，不向后面的无关段落传播。显式引用优先于继承来源。继承引用仅表示背景，不能让常识、示例和建议被强制要求逐行摘录；明确复述资料的事实仍需对应依据。表头、分隔行和纯标签可判非事实。草稿标题/摘要不跨字段建立继承范围。

表格内显式引用限定在单元格中，列表内显式引用限定在当前条目，不能把B单元格/条目的引用套给前面的A。行内代码和转义竖线不分割单元格；最后一个表格分隔符外的引用按整行来源处理。前置引导/后置来源仍为没有显式引用的单元提供背景。含“路径/步骤”等词的普通事实不能仅凭关键词当成标签；只有确实引出后续内容的冒号结构才使用该标签作用域。

evidence_ids 必须对应后端生成的真实来源正文、标题或 URL 片段，不能用另写的自检摘要替代正文核验。引用合法但原文不支持、条件被夸大、数字或版本不匹配也可进入修正。核验模型不具有工具或写入权限。

修正后再次检查引用、执行事实、逐条结论及文章版本。内部 `delivery_evidence` 在核验结束前保留 Main 选中的真实来源及本次受控补检索取得的来源，允许将错引 A 修为支持结论的 B，不能使用该集合以外的来源；最终持久化时只保留修正后实际正文使用的引用和文章卡片。用户停止、权限错误和运行 Token 预算耗尽仍向外传播。

## 局部保留与核验故障

补检索完成或不适合补检索时，使用已有的一次修正调用重写受影响的完整段落，连同依赖该前提的后续结论一起处理。保留可确认内容，在原来需要结论的位置自然说明仍缺少什么资料、哪些内容尚无法确认，而不是简单删句后在末尾统一提示。不能只加“可能”继续保留未经证实的数字；修正阶段不再追加检索或额外生成调用。修正后仍执行一次完整复核。

一次修正后仍有局部问题，程序从最近一次合法核验结果中保留可靠内容。单行普通说明段按完整句子投影：通过后端真实单元位置判断句子是否涉及失败单元，保留其他完整已核验句子。分号及括号内的条件不拆开，引用随句子保留；若有效引用原本落在被替换的句子末尾，为保留的有据内容补回引用。依据不足的句子在原位置替换为后端固定的信息缺口说明；相邻同类缺口合并，避免反复提示。前提无法确认时，明显依赖它的“因此/据此/该方案”等后续句子保守收掉。引号、括号、强调符号无法完整定位时，放弃局部投影，整段改为限制说明，避免拼出半句话。

表格、代码、列表、HTML和多行结构不按字句剪贴；依据不足的块整体替换成该处的限制说明，并保留所属章节，不交付截断代码或残缺表格。矛盾、错源、执行状态错误仍纠正或收掉，不以“资料不足”掩盖已知错误。清理孤立引导标签和来源脚注，限制说明本身不沿用被拒绝内容的引用。信息缺口已在局部说明时不再追加笼统的“部分细节已省略”；确有错误或核验服务故障仍追加相应提示，原有检索范围提示保留。只有实际保留的实质内容计入通过部分的判断；仅剩限制说明时保持unverified/verification_unavailable，不能标partial或verified。有据草稿不使用局部限制替换后审批或发布，仍需完整通过。

uncertain表示资料不足、尚不能确认，不等于已证实错误；仅剩这类问题时记录reason_code=evidence_uncertain。unsupported或混合的依据不足记录insufficient_evidence。核验模型对两类问题额外选择missing_information固定分类：实测数据、完整原文、版本说明、实际配置、用户条件或直接支持的资料。后端按分类渲染限制说明，不展示模型原始评语，不重复待核验的数字、链接或断言；旧核验结果未提供分类时使用通用资料缺口说明。矛盾、错引、执行状态冲突等仍记录content_rejected。后端校验错误优先，不能因模型同时标uncertain而被降为普通不确定。资料范围提醒结合执行记录检查，不强迫其从文章中寻找逐字依据。

核验超时、结构/依据编号不合法、上下文预算不足、服务异常分别记录 reason_code，不再一律写成“事实错误”。修正或复核故障时，若首轮已完成核验，保留其已通过的原文部分。首轮核验即发生故障，且没有后端执行事实错误、没有明确证据不足时，普通回答保留原始正文并附“自动依据核验暂未完成，请结合引用来源判断以上内容”；status保持 verification_unavailable，fallback_policy=answer_with_notice，绝不标为已核验通过。引用合法性、访问权限和来源版本仍由 final_gate 强制检查。已知错误、证据不足、修正失败及草稿审批/保存不走此分支。没有可用部分时给出简短限制说明，不再倾倒原始资料、内部引用或截断代码。

| grounding_audit.status | 含义 |
| --- | --- |
| not_required | 普通无来源闲聊，无需额外核验 |
| verified / repaired | 完整核验通过 / 一次修正后通过 |
| partial | 保留已核验的完整句子/结构块，提示尚未确认的细节、缺乏依据或核验故障 |
| unverified | 确认仍有内容问题，且无实质内容可保留 |
| verification_unavailable | 自动核验未完成，不能推断原回答已被判错 |

审计 version=11，新增lookup_count及lookup_status记录补检索次数和实际状态；记录分类计数、问题计数、failure_phase、reason_code及failure_detail。局部交付额外记录omitted_block_count、partial_block_count、omitted_sentence_count，分别统计不再按原文交付的块、局部保留及替换/删除的完整句子数量；limitation_block_count、limitation_count记录原位信息缺口说明所在块数和次数，fallback_policy=inline_limitations。safe_blocks仅保存可靠原文；limited_blocks单独保存附加后端限制说明的展示文本，不能把限制说明计为已支持事实。initial_issues、remaining_issues保留首轮/复核问题类型计数；initial_findings、remaining_findings保留block_index、unit_index、kind、verdict、固定issue_code、hard_error及missing_information，便于定位哪一处因资料范围、归属、矛盾或执行状态被拦。不记录实际结论、任意原始评语或来源摘录。citation_repair_blocks记录本地补引用块数。failure_detail仅为后端白名单诊断码，如 unit_coverage、unknown_evidence、missing_evidence。

## 资料限制

- `adequacy=none`：仍可核验后交付明确的通用解释或条件性建议，并追加未基于本次检索验证的提示；不能把无结果扩大成“文章不存在”。
- `partial`：追加部分覆盖提示。
- `conflicts`：只能引用已选择的不同来源，未解决冲突时必须为 partial；正文揭示矛盾，追加冲突提示。
- 联网 error：追加未完成核验的提示，不能写成搜索后无结果。
- 联网引用记录 `contentScope=search_excerpt`，追加尚未核验网页全文的提示。此改动没有自动抓取网页全文。

## 草稿

有据草稿在生成后、进入 interrupt 审批前核验标题、摘要及正文 JSON，使用原始证据正文而非中间分析作为事实依据；无法核验就不进入审批和保存。通用原创、没有引用的草稿不强制核验所有常识。

用户手工修改后，仅执行原有引用和来源检查，不在点击批准后偷偷改写其正文。审计状态标记 `user_edited`，不能沿用生成版本的语义核验结论。审批恢复与数据库保存的行为不变。

## 持久化与边界

`grounding_audit` 在 Checkpoint、运行结果及进度快照保留状态、调用尝试计数、正文哈希及错误类型，不保存核验提示词或原始评语。草稿审计随写作任务结果保留。需要依据核验的候选回答及生成中的草稿不向前端发送正文预览；前端先展示活动进度，运行结算后再接收最终回答，草稿核验通过后才展示审批内容。前端继续忽略历史运行重放的旧 `__PREVIEW__` 帧。

普通无来源直接回答支持同一次Main模型调用内的实时正文输出，不新增动作或模型调用。后端仅为首轮、没有当前任务结果、文章上下文、补检索或记忆写入状态的Main调用开放流式资格；普通历史消息及尚未选用的上次运行结果不禁用流式，选择复用旧结果的回答继续缓冲。Main先完整输出动作、证据、依赖、记忆变更等字段，用户正文最后输出；模型线路使用`user_reply`别名兼容字段按名称排序的模型，内部状态、历史和API仍使用`reply`。解析器只有在这些控制字段均明确为空、动作为answer且后端资格标记有效时，才发送正文增量；每批实时正文发布前仍校验运行状态和执行代次。字段缺失、顺序不合要求或包含依据/执行请求时，回退到结算后交付。模型推理、工具参数、引用修正及核验文本不公开。

实时正文使用现有`__ANSWER__`的start/delta/end协议，首块直接发送，后续按已有合并间隔发送；前端给正文分块让出绘制机会。最终仍执行原有契约、执行事实和final_gate检查，结算后以`__REPLY__`为权威正文；一致时不清空重发，不人为增加打字延迟。实时分块沿用运行事件持久化和游标重放，断开HTTP订阅不终止后台运行；生成期间内容不代表运行已经成功，取消或故障仍显示对应状态。

执行轮数、任务数、重复策略或格式修正达到上限时，由后端生成固定停止说明，明确尚未完成全部要求；可附最多4个已成功、经Main选择并按文章/URL去重的来源入口，不拼接标题、正文摘录、分析产物或文章卡片。已成功任务仍留在状态中供后续恢复使用，停止说明不冒充综合答案。

只有白名单停止原因生成的 `backend_boundary`，且与当前请求身份、停止原因、完整模板、所选引用和 `delivery_evidence` 严格匹配，才跳过语义核验，记录 `reason_code=backend_boundary`、零核验/修正调用。取消检查、引用合法性及来源版本检查仍执行；普通模型正文和新请求清空该标记，单独的stop_reason或正文哈希不能绕过核验。记忆写入提示仅允许对应真实pending/failed状态的固定后缀。

该层仍然使用模型进行语义判断，可能误判或错误拒答。单元覆盖、引用绑定与依据编号真实性是程序校验；结论分类、单元内所有事实是否成立、前提是否可靠及推理是否成立仍由模型判断，并非数学证明。错误内容可能被误分类为常识或建议，需持续收集误放行和误拒答样例。普通回答在核验服务故障时可能带未完成提示交付，不能将其统计为核验通过；来源不足或已知错误不因此放行。执行状态的自然语言断言检查也只覆盖明确模式，不能识别所有同义表达。来源本身可能错误，合法依据也不保证客观事实正确。

## 测试与评测

2026-10-12 普通回答实时流式改造验证：最终后端离线测试641项通过，网络拦截记录为空（`logs/agent-offline-direct-stream-20261012-final.log`）；前端会话和流协议12项测试及生产构建通过。最终3个合成真实模型场景均在模型结束及运行结算前输出正文，分块拼接与最终正文一致，每个场景只有一次模型调用（`logs/evaluation/direct-answer-stream-live-20261012-5`）。这只验证流式交付行为，不是事实准确率或一般性能指标。字段顺序不满足要求时仍保守缓冲，既有调试失败记录保留。

2026-10-11 本次交付补检索与段落补丁改造验证：后端离线测试 631 项通过，网络拦截记录为空（`logs/agent-offline-delivery-recovery-20261011-2.log`）；前端会话与流协议测试 12 项通过，生产构建通过。另对两个独立合成错误候选执行真实核验、段落修正与复核，均完成修正（`logs/evaluation/grounding-paragraph-patch-live-20261011/summary.json`）。真实模型检查只覆盖这两个合成候选；完整补检索路由由生产图的脚本化集成测试覆盖，不能据此推导线上准确率。

在 `python-agent` 目录运行：

```powershell
# 禁止进程访问网络；仅允许 Windows asyncio 自唤醒 socketpair
.\.venv\Scripts\python.exe ..\scripts\run-agent-offline-tests.py

# 65个固定合成案例，真实图与后端门禁，Main/检索/核验响应回放
.\.venv\Scripts\python.exe -m evaluation.grounding --mode replay --output ..\logs\evaluation\grounding-replay-new

# 真实核验/修正模型，Main及检索仍为固定回放；不操作数据库、不联网搜索
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids cache-supported cache-contradicted web-failure partial web-excerpt approval-source_injection --output ..\logs\evaluation\grounding-live-new

# 引用绑定与逐条结论的真实核验/修正模型测试
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids cache-supported cache-contradicted wrong-source multiple-conclusions source-conflict approval-source_injection --output ..\logs\evaluation\grounding-binding-live-new

# 分析、建议、常识与错误事实混合回答的真实核验模型测试
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids recommendation-without-direct-quote derived-conclusion mixed-general-knowledge no-evidence-conditional-advice false-fact-disguised-as-advice wrong-source cache-contradicted source-conflict --output ..\logs\evaluation\grounding-policy-live-new

# 独立编写的长 Markdown + 完整 Java 示例 + 表格，及越界引用/错误事实
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids long-code-and-table cache-contradicted wrong-source recommendation-without-direct-quote --output ..\logs\evaluation\grounding-ids-live-new

# 引导标签/表格脚注/学习步骤的引用范围，错源引用仍需修正
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids scoped-table-intro-and-steps scoped-table-footer-and-steps wrong-source long-code-and-table --output ..\logs\evaluation\grounding-scope-live-new

# 独立编写的教学表格/示意JSON/学习建议，无逐字来源也应完整保留；真实指标仍需依据
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids knowledge-with-examples knowledge-with-background supported-fact-missing-reference wrong-source false-fact-disguised-as-advice --output ..\logs\evaluation\grounding-common-live-new

# 数字列表及共享引用不能触发“每句必须用全部来源”的误删；真正错引仍需修正
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids shared-citations-learning-list knowledge-with-background wrong-source --output ..\logs\evaluation\grounding-shared-live-new

# 资料说明中的局部疑点、有据流程混入虚构指标：应保留说明及可靠内容，修正具体断言
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids scope-note-one-uncertain-sentence same-paragraph-conflicting-metric knowledge-with-background wrong-source --output ..\logs\evaluation\grounding-projection-live-new

# 信息缺口应在原段落说明，保留章节和有效建议；常识与错源作为对照
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids measurement-gap-at-original-position version-gap-with-section-context knowledge-with-background wrong-source --output ..\logs\evaluation\grounding-limitations-live-new

# 原文也可能错误：明显算术错误、准确转述并纠错、排名不证明真实性；真实核验/修正模型
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids source-supports-obvious-error accurately-report-source-error ranking-is-not-truth-proof wrong-source --output ..\logs\evaluation\grounding-source-quality-live-new

# 推理也可能错误：条件偷换、局部异步泛化、完成标记与业务之间的崩溃窗口
.\.venv\Scripts\python.exe -m evaluation.grounding --mode live --ids do-not-confuse-staleness-with-latency partial-async-is-not-entire-request-async idempotency-marker-before-business-window --output ..\logs\evaluation\grounding-reasoning-live-new

# 7个独立合成资料场景：真实Main决策+交付核验；只预置资料，不执行真实检索或读写数据库
.\.venv\Scripts\python.exe -m evaluation.answer_synthesis --mode live --output ..\logs\evaluation\answer-synthesis-live-new

# 同一组场景的脚本回放，仅验证Main契约及最终门禁
.\.venv\Scripts\python.exe -m evaluation.answer_synthesis --mode replay --output ..\logs\evaluation\answer-synthesis-replay-new

# 3个独立合成问题，真实Main模型与流式链路；禁止工具执行和应用数据库读写
# 检查正文在模型结束/运行结算之前出现、正文一致且未新增模型调用
.\.venv\Scripts\python.exe -m evaluation.answer_stream --output ..\logs\evaluation\direct-answer-stream-live-new
```

输出 manifest、逐条预测、summary 和人工评审模板。记录原始候选、来源、最终回答、调用次数、Token 和耗时，失败样例保留。回放的行为断言通过率不能写成模型事实准确率；live 模式只测固定候选上的核验/修正，不是线上全链路成功率。证据支持率保留空值，待人工逐条标注后计算。

`answer_synthesis` 的范围单独标记为 `seeded_context_main_decision_and_delivery`：live让Main生成答案，再走实际final_gate；检查概念解释、条件性取舍、重复观点合并、来源FIFO/算术错误、摘要版本不足及用户明确要求资料列表。意外的非answer动作只记录失败，不派发工具。所有问题和资料独立编写，run_id、articleId及历史为空，数据库和记忆写入被禁止。关键词/结构断言只是冒烟检查，不能当作综合质量、事实准确率或线上全链路指标；候选和最终正文保留供人工审读。

2026-10-11审读另存于 `logs/evaluation/answer-synthesis-review-20261011.jsonl`：自动断言通过的比较回答仍出现把数据过时容忍度当成请求延迟容忍度、局部异步泛化；教学去重建议也出现未处理完成标记与业务之间失败窗口的情况。新增固定错误候选能被核验并修正，不代表Main实际生成的所有同类错误都能被识别；当前综合形式改善，语义核验仍有漏判。这些记录是Agent审读，不是独立人工真值标注，不应合并成“准确率100%”。
