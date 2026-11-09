# 草稿直接编辑与本人草稿访问

AI 草稿审批卡片提供“直接编辑”，弹窗复用写文章页的 ArticleRichEditor（WangEditor），允许修改标题、摘要及富文本正文，支持工具栏、代码、表格和图片上传。弹窗使用独立编辑副本，应用后更新聊天预览，取消不改动已应用版本。未修改正文时保留原 Markdown；修改后通过 `editedDraft.content_format=html` 明确提交 HTML，Python 不再将其作为 Markdown 转义，Java 在文章保存边界继续统一清理 HTML。仅编辑不调用模型；继续让 AI 调整时，生成节点接收手动修改后的完整版本，重新生成并再次暂停等待审批。

审批仍绑定原 `runId` 和 `draftHash`。Python 在领取恢复执行权前检查字段及新增引用；恢复后的审批节点重新渲染并计算编辑版哈希。保存网关携带原审批哈希 `baseDraftHash` 和编辑版 `draftHash`；Java 在会话与运行事务锁内核对原版本、执行令牌和截止时间，保存后记录编辑版哈希，支持响应丢失后的幂等重试。

已有草稿通过 `retrieve(target="drafts")` 访问，不增加新 action。没有 article_ids 时按标题列出本人最近 20 篇工作草稿；提供一个真实 ID 后读取完整工作版本。Java 内部接口使用服务凭证与可信 user_id，重新核验文章所有者；私有草稿不走公共 ES 索引，不提供公共引用或联网权限。

修改已有草稿必须声明 `draft_source_task_id`，并将该成功读取任务列为依赖。后端从读取结果获取 article_id、revision_id 和 editable，不能由模型直接指定覆盖目标。审核中的版本只读。载入的实际序列化全文超过任务结果或生成预算时返回资料不足，引导使用文章编辑器，不截断后覆盖。

写回已有草稿时使用同一 article_id 和 expectedRevisionId，复用 ArticleRevisionService 的版本校验与追加快照流程，保留分类、标签、封面及原创属性。已发布正文不会被修改草稿直接替换；后续仍需提交审核。

保存失败后前端保留手动内容并允许复制。若审批预览已被其他窗口更新，旧编辑内容单独保留，不自动套用到新版审批。尚未确认的手动编辑仅存在当前页面内存中，刷新前应先保存或复制。

## 验证

- Python：`test_private_drafts.py` 覆盖本人全文读取、隔离权限、超长拒绝、原草稿审批写回及双哈希；`test_phase0.py` 覆盖手动版本交给 AI 修改、新审批及无效引用在领取运行前拒绝。
- Java：AgentBoundaryTests / ArticleRevisionTests 覆盖审批版本、幂等、原文章 ID 写回、所有者校验、待审核只读、版本冲突及元数据保留。
- 前端：真实 SFC 测试覆盖编辑/预览/提交；`tests-e2e/draft-edit.spec.ts` 在隔离 API 数据下验证实际聊天页桌面端、手机布局及失败恢复，不调用真实模型或修改用户文章。
