# DeepSeek 联网检索

联网搜索已从博查切换到 DeepSeek Search。当前 Python Main Agent 仍决定是否检索、筛选来源和评估覆盖范围；搜索服务返回的排序分数不代表事实核验通过。Java 兼容检索工具也使用相同的 Search API。

- `POST https://api.deepseek.com/v1/tools/search`：共用 `DEEPSEEK_API_KEY`，请求 `need_content=true`，默认 5 条结果。
- 搜索词为 1–128 个 Unicode 字符，保留站点、时间和排除条件。超过限制时改写或返回明确错误，不直接截掉筛选条件。
- Python 对缺少正文的前两条有效结果并行调用 `POST /v1/tools/fetch`；已有正文时不重复抓取。抓取失败保留原搜索摘要，不把摘要称为网页全文。
- 页面内容限制为 4000 个本地估算 Token、最多 16000 字符。超限正文标为 `page_excerpt`，未截断的返回正文为 `page_content`，只有搜索摘要时为 `search_excerpt`。正文是否正确仍由交付核验判断。
- 引用预览最多 1200 字符；生成、依赖任务与独立核验使用同一份已取得、经过预算裁剪的原始内容，不使用预览替代正文。
- Search 总超时 16 秒；可选 Fetch 总超时 8 秒、并发 2。网络错误、408、429、5xx 最多重试一次；其它 4xx 不自动重试。错误不输出密钥或服务商原始响应。
- Python 每个进程对 Search 和 Fetch 分别使用 5 次/秒的滚动窗口限流。官方限制是账号级且 Fetch 还有目标域名限制：多实例共用账号时，本地限流不能代替全局配额，仍可能收到 429，由有界重试和降级处理。扩容时需要共享限流或为各实例分配配额。

配置：`DEEPSEEK_TOOLS_BASE_URL` 默认 `https://api.deepseek.com/v1`，独立于聊天模型的代理地址；Java 配置为 `agent.web-search.base-url`。联网开关与任务能力白名单继续生效，平台作者/分类/指定文章等强制过滤条件不会被网页检索扩大。

Search 是文本搜索，不提供以图搜图。图像理解由 DeepSeek 模型直接完成，Main 可以根据图像观察生成文字检索词。

Main 对缺少依据的出处、作品归属等查证请求，应根据可辨认的文字和视觉线索先尝试检索，不要求用户额外说“联网”。不能仅凭水墨风格、拼贴构图或缺少水印判断图片是 AI 生成、原创或非官方；搜索无明确依据时保持未确认。描述颜色、翻译已提供文字等任务继续直接回答；联网禁用、用户约束或原图缺失时说明实际限制。`retrieval_policy` 向 Main 提供真实开关以及仅支持文字搜索的能力范围，不授予工具权限。

官方文档：[Search / Fetch 使用指南](https://api-docs.deepseek.com/zh-cn/guides/search/)。

验收：`scripts/deepseek-search-smoke.py --live` 使用固定的公开查询验证真实 Search 和 Fetch；`scripts/search-chat-http-smoke.py --live` 创建临时账号，经网关/Java/RPC 发起一次真实公开检索对话，检查正文、独立核验、流式输出与落库，再清理自身数据。两者需使用项目 Python 虚拟环境运行，`--live` 表示允许消耗接口额度。报告分别写入忽略目录 `logs/deepseek-search-smoke.json`、`logs/search-chat-http-smoke.json`，不记录密钥和用户私有内容。

添加 `--image-lookup` 时，后一个脚本使用合成的公开技术文字图片，只问原始出处而不明说“联网/搜索”，验证 Main 能自行选择检索；报告写入 `logs/image-source-chat-http-smoke.json`。合成图片不包含用户上传的私有素材。

动作校验失败时，Main 最多修正一次。修正上下文包含具体字段错误、被拒绝的控制参数，以及按任务分组的合法引用编号；任务编号与引用编号不能混用。`selected_ids=[]`、`adequacy=none` 是“检索完成但资料无法证明目标”的合法状态，不要求选择无关资料。失败记录仅保存阶段、字段路径和错误类型到 `decision_contract_audit`，不保存模型原始回答或隐私内容。两次仍不合法时不执行错误动作；已取到候选资料的情况按真实进度说明尚未完成答复，不把内部格式错误直接当成业务结论。

`scripts/decision-contract-replay.py --run-id <id> --live` 从已有检索后的 Checkpoint 只读回放 Main 与交付核验，不重复检索、不更新原运行或会话，不执行记忆/草稿写入。可加 `--inject-invalid-first` 人为制造一次资料选择不一致，验证真实模型能根据字段错误完成有界修正。该回放会把原运行上下文发送给当前配置的模型提供方，需显式 `--live`；输出报告仅保留状态与诊断编号。
