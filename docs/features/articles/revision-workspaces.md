# 草稿、审核与发布存储

## 新文章

后端生成稳定的 article_id；首次保存只 INSERT article_revision，不创建 article_info。
同一工作草稿反复保存更新原行，实际内容变化时 lock_version 递增，正文无变化不写入。
提交审核冻结当前工作草稿，不复制正文。待审核不可编辑；撤回或驳回后，下一次编辑创建新工作稿，原审核记录及正文保留。
首次审核通过，在同一事务内创建 article_info、更新发布指针、增加作者文章数、记录审核日志及写入索引 outbox。

## 已发布文章

article_info 保持当前公开正文、阅读门槛、发布时间与互动计数。
修改时从公开版本保存一份工作稿，仍关联同一 article_id；未通过审核不改变公开内容。
后续审核通过只更新公开内容与发布指针，不重复增加文章计数或覆盖首次发布时间。
丢弃修改回到已发布 head；恢复历史内容先写工作稿，仍需审核才公开。
删除文章会同步隐藏其 revision 工作区并记录 delete 日志，避免已删除文章从草稿入口复活。

## 并发与 Agent

revision_id 标识工作稿/冻结版本，version_no 标识版本序列；lock_version 标识同一工作稿的内容变更。
编辑、提交与恢复请求必须同时携带 expectedRevisionId 与 expectedLockVersion。
Java 按作者行 → 公开文章行（存在时）→ 当前 revision 的顺序加锁。作者锁用于序列化尚无公开主行的首次发布与工作稿创建；事务内不执行 LLM 调用。
is_current 由唯一生成列 current_article_id 约束，每篇文章最多一条有效当前版本；历史版本保留。

Agent 读取本人草稿走 Java 私有接口，返回全文、状态、revisionId 和 lockVersion。
这些字段随 target_draft 进入写作子图和 Checkpoint，确认保存时后端重新校验所有权、状态与锁。
确认期间如果普通编辑器已修改、提交、撤回后新建或删除草稿，则旧确认失败，不自动覆盖。
AI “确认保存草稿”不等于文章“审核发布”。agent_run 的保存回执保证同一确认重试只写一次。
旧 Checkpoint 若缺少锁版本会拒绝保存，需重新读取生成；不猜测或补取最新锁后自动覆盖。
遗留 Python 直写 article_info 草稿入口已停用，生产保存统一走 Java 网关。

## 其他入口

- 草稿箱和 Agent 草稿列表查 revision 当前工作区，按 updated_at 排序。
- 审核队列使用 LEFT JOIN info，尚未首次发布的稿件不会漏掉。
- 后台文章管理只管理已发布/下架内容；未公开数量统计 revision 中尚未发布的文章，不把修改稿重复计为新文章。
- 首页、个人公开文章、公开搜索和 RAG 继续读取公开 info，保存工作稿不投递公开索引更新。
- 评论、点赞、收藏、会话消息中的草稿链接继续沿用原 article_id。
- 历史审核版本及日志本次不自动裁剪；后续正文保留策略需明确哪些审核证据必须保留。

## 迁移 020

先停止 Java/Agent 写入，再执行 `scripts/apply-revision-workspace-migration.py`。
迁移添加工作区字段、唯一索引，补全旧 AI 草稿缺少的 revision，并保留所有原 info 行、正文和标签关联。
脚本验证迁移前后的原文及关联摘要一致，并验证重跑不新增版本。
旧未发布 info 行暂作兼容记录；新的草稿不会再创建这种记录。
历史清理尚未执行，避免未经备份验证删除旧数据。清理前必须准备可恢复备份及精确待处理清单。

## 验证

- `mvn '-Dtest=!EasyjobApplicationTests' test`（不包含依赖外部环境的 Spring 全上下文测试）
- `python scripts/article-review-check.py`：本地 HTTP/MySQL、隔离用户和文章，审核/撤回竞态、工作稿复用、版本校验、计数及通知。
- `python scripts/agent-draft-workspace-check.py`：真实内部服务接口、隔离 Agent run，无 LLM 调用；确认重试、私有读取、锁冲突、元数据保留及删除保护。
- `python -m unittest discover -s tests -p test_private_drafts.py`：生产写作图的 Checkpoint 恢复和网关锁参数传递。
# 数据访问分层

草稿与审核 SQL 位于 `ArticleRevisionMapper.xml`，Agent 保存凭据 SQL 位于
`AgentDraftMapper.xml`，关联的后台文章管理和统计 SQL 分别位于
`AdminConsoleMapper.xml`、`AdminStatisticsMapper.xml`。
对应 Service 通过 Mapper 接口调用持久化操作，负责权限、状态转换、内容校验和事务；
不再直接使用 JdbcTemplate 或拼接查询字符串。筛选条件使用 XML 动态 SQL，值通过
`#{...}` 绑定，不接受调用方传入 SQL 片段。

新版本插入使用 `ArticleRevisionInsert` 接收生成主键，发布投影使用
`PublishedArticleProjection` 传递强类型参数。现有查询结果和 HTTP 响应字段保持兼容。
作者、公开文章、当前版本的加锁顺序，以及审核、计数、日志和索引事件的事务边界保持一致。
本次分层重构不修改数据库结构或清理历史数据。
