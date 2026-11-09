# 推荐与阅读量同步

## 首页推荐

推荐会读取用户画像中的关注领域，同时保留近期阅读、点赞和收藏形成的标签偏好。关注领域按大小写去重，兼容旧版 `tech_stack` 与 `interests`；修改或删除后在下一次推荐请求生效。

领域通过标题中的字面匹配或文章标签精确匹配参与排序。英文词有边界限制，例如 Java 不会匹配 JavaScript。明确关注领域加 3 分，近期互动标签加分最多 6 分，结合热度、时间衰减与新文章加分；近期读过的文章降权。以上为可调整的初始规则，并不代表已经验证点击率提升。

推荐首先按当前可读性排序，再按推荐分排序，仍然保留未解锁文章的发现入口。“只看可读”在 SQL 中过滤后再分页，同时适用于推荐与普通文章列表。游客按 L0 判断；作者可读自己的已发表文章，有效管理员不受阅读等级限制。用户身份来自服务端验证的登录令牌。

## 阅读量同步

符合计数规则的新阅读，在同一事务中更新 MySQL 阅读量并写入 `article_view_sync`。同一文章只有一个待同步记录，保存目标累计值，连续阅读会合并。既有的读者、文章、日期去重规则和作者自阅不计数规则继续生效。

后台每秒轮询，一批最多处理 10 个任务，通过 `FOR UPDATE SKIP LOCKED` 和 30 秒租约领取。ES 只更新计数字段，不重建正文或向量。ES 更新只允许计数增加，旧任务不能覆盖新计数；确认任务时也会保留领取后到达的更大目标值。

ES 不可用或文档尚不存在时，任务保存在 MySQL，按 2 秒起的指数退避重试，最长间隔 5 分钟。进程重启后过期租约可重新领取。删除、未发表或不存在的文章不会被计数任务重新创建到搜索索引中。

部署前应用 `python-agent/migrations/013_article_view_sync.sql`。本地可使用 `scripts/apply-view-sync-migration.py`，仅应用该迁移并检查重复执行。

## 验证

- `ArticlePreferenceTests`、`RecommendationTests`、`ArticleReadTests`、`ArticleViewSyncTests` 覆盖关注领域、权限参数、阅读去重与租约确认。
- `scripts/recommendation-access-sync-check.py` 使用隔离的临时用户和文章验证真实 Java HTTP、MySQL 和 ES：关注领域冷启动、删除生效、访问角色、筛选分页、20 路重复阅读、ES 缺失重试及恢复追平。脚本在结束时清理自身测试数据。
- `scripts/recommendation-reading-check.py` 回归既有阅读计数与行为推荐规则。

本轮新增集成验证 22 项全部通过，相关 Java 测试 31 项全部通过，前端构建成功。报告位于 `logs/evaluation/recommendation-access-sync-20261005-201054.json`。
