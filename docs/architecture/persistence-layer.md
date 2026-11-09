# Java 数据访问分层

Java 业务代码不再直接使用 JdbcTemplate、原生 JDBC 或 SQL 注解。
普通单表 CRUD 可以使用 MyBatis-Plus；手写查询、分页、更新、行锁、租约条件均放到 Mapper XML。
Controller 负责参数与响应，Service 负责权限、业务规则和事务，Mapper 负责数据库访问。

此次覆盖剩余文章阅读、阅读成长、权限、用户画像偏好、推荐反馈、后台分类、后台用户、
运行管理、Agent 指标，以及文章索引 Outbox、阅读数同步队列。
搜索通过 `ArticleSearchService` 回查权威数据库，Controller 不再执行查询。
原 AiConversation、Conversation、Message、User Mapper 的 SQL 注解也已移入各自 XML；
通知未读列表中的 limit 片段移入 NotificationMapper XML；
正文分块重建的游标分页查询移入 ArticleMapper XML。

动态筛选使用 `if/choose/foreach` 与 `#{...}` 参数绑定。
运行队列只允许 article、memory，对应表名是 XML 中的固定字面量，不使用调用方提供的表名或 SQL 片段。
查询和计数共享筛选条件；任务领取继续使用事务及 `FOR UPDATE SKIP LOCKED`，
完成、重试继续校验租约令牌，阅读去重继续依赖唯一键与 INSERT IGNORE。

MySQL 索引锁由 `ArticleIndexLock` 封装。它持有一个 SqlSession，在同一连接上获取并释放命名锁，
异常时也释放后关闭会话；未获取到锁时不执行索引、不释放其他执行者的锁。
锁查询禁用二级缓存并清空一级查询缓存，避免把先前的 GET_LOCK/RELEASE_LOCK 结果当成新调用。

阅读心跳显式映射 Timestamp 与 Boolean，保持原有计时逻辑。
本次不修改数据库结构或历史数据，不改变草稿、审核和公开文章的边界。

验证包含既有单元测试、搜索/锁专项测试、XML 动态条件测试与分层回归检查。
`PersistenceLayerTests` 防止 Java 业务代码再次加入 JDBC、SQL 注解或 Wrapper.last 手写片段。

本地真实接口回归可使用 `scripts/mapper-layer-check.py`，覆盖管理指标的三种来源、
用户资料与阅读时长的并发校验、分类迁移及审计；样例在 finally 中按测试身份清理。
其他回归入口包括 reading-level、recommendation-reading、recommendation-access-sync、
admin-console、maintenance、article-review、agent-draft-workspace 和 message-delivery 的 check 脚本。
这些检查验证功能与数据一致性，不代表负载或性能基准。
