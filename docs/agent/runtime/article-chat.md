# 文章详情问答

## 会话与入口

文章详情页右侧提供私密的「问 AI」面板，同时保留公开读者聊天室和在线人数。手机端使用浮动入口与抽屉。面板复用 AiChat 组件与现有 SSE 协议。

宽屏面板从原在线栏的左边缘展开到窗口右侧，保留 20px 外边距。原在线栏在面板打开时隐藏但保留布局占位，目录与正文不重排、不改变宽度。根据实际可用空间判断是否并排展示；右侧不足 360px 时使用覆盖式抽屉。ResizeObserver 与窗口 resize 更新定位，组件卸载时清理监听。

打开文章、打开面板、点击新话题都不会创建空会话。只有发送第一条消息才创建；再次打开同一篇文章时，恢复当前用户在该文章下最近有消息的会话。新话题在下一次发送时创建新的会话。

独立智能助手将会话分为「普通聊天」与「文章问答」，每组分别分页。面板中的「在智能助手中展开」携带 conversationId，读取同一份历史，没有复制会话。

## 文章来源不限制检索范围

迁移 006 增加可空的 ai_conversation.origin_article_id，以及用户、来源、状态、更新时间和会话 ID 的非唯一索引。同一篇文章可以有多个话题。现有普通会话保持空来源。

首次发送可以传 originArticleId（Java）/origin_article_id（Python）。后续请求可以省略，由后端根据用户所有权读取已保存来源；显式传入不同来源会被拒绝，不能悄悄改绑已有会话。

每次新执行从共享 MySQL 读取来源文章的当前公开版本，提取 HTML/Markdown 的可见正文及代码。摘要、引用和正文证据交给 Main；来源不是权限或搜索范围。

Main 仍按 answer/retrieve/delegate/write_draft 决策。RetrievalRequest.article_ids 默认为空，表示全站知识检索；需要限定文章时显式传已知 ID，最多 8 篇。知识 KNN 与 BM25 共用该过滤条件，返回候选后再次按 MySQL 公开状态、版本和范围核验。记忆检索与非搜索任务不能使用 article_ids。

因此「解释本文」可以直接基于正文回答；「和另一篇比较」可以检索另一篇并引用两篇；「现在聊 Redis」仍可正常切换话题。

## 边界

文章正文默认最多 32,768 tokens（AGENT_ARTICLE_CONTEXT_MAX_TOKENS），标记完整或节选；超过这个上限的文章仍按需检索对应文章片段，不会标成已读取全文。来源文章与系统提示、工具结果、历史等一起受整体上下文预算检查。正文只放在来源证据中一次，article_context 保存元数据。该证据不占执行任务名额。

每次读取遵守已发布、未删除规则。新会话引用不可读来源时不创建会话、不追加消息；已有会话的来源下线后，保留用户自己的历史，明确标记来源不可用，允许继续讨论其他内容。旧历史不能充当当前版本的证据。

来源正文参与现有引用与 sourceHash 最终校验，防止引用已删除、下线或改变的正文。文章中的图片不会自动识别为视觉内容。

## 本地验证（2026-10-02）

- Python 278 项、Java 52 项、前端协议 12 项回归测试通过；前端构建通过。
- 3 轮 API 真实问答覆盖本文解释、跨文章比较、无关话题；浏览器另完成 1 轮实际 SSE 问答。
- 验证空面板不建会话、新话题发送前不建会话、展开共用 ID 和消息、分组、390×844 手机抽屉及读者聊天室在线状态。
- 错误来源、未发布来源、其他用户会话请求被拒绝且不追加消息。
- 临时测试账号、文章、会话、运行记录、检查点和后台任务已清理。

这些是功能验证，不代表大样本回答准确率或延迟百分位。API 单次解释、比较与换话题结果及耗时位于 logs/article-chat-live.json；界面截图位于 logs/article-chat-desktop.jpg 与 logs/article-chat-mobile.jpg。

可在已运行的本地开发服务上复验。脚本依赖已有 RAG 评测样例，只创建专用临时账号和文章，通过本地配置签发测试令牌，不打印令牌。

```powershell
.\python-agent\.venv\Scripts\python.exe scripts/article-chat-smoke.py setup
.\python-agent\.venv\Scripts\python.exe scripts/article-chat-smoke.py api
.\python-agent\.venv\Scripts\python.exe scripts/article-chat-smoke.py inspect
.\python-agent\.venv\Scripts\python.exe scripts/article-chat-smoke.py cleanup
```

测试清单保存在 temp/article-chat-fixtures.json；出现中途失败时保留它，按该清单 cleanup，避免修改现有用户的数据。
