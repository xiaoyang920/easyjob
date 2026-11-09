# HTML 结构分块与同粒度 RRF（已实现）

## 当前链路

Java：当前公开文章 HTML → Jsoup DOM 分块 → 标题路径 + 块正文 Embedding → `article_vectors`。

Python：Query Rewrite → 同索引 KNN / BM25 → chunk_id RRF → MySQL 校验公开状态、正文 Hash 和元数据 → Reranker → 块引用及完整上下文 → Main / Search Subagent 生成 → 交付前再校验正文版本。

博客搜索页继续使用 `article` 索引。RAG 关键词检索改用 `EsChunkSearch`，不会再将文章级摘要和块级正文当作同一种候选融合。

## 分块规则与边界

| 项目 | 当前行为 |
| --- | --- |
| 基础单位 | HTML `p` 段落；递归遍历布局容器，保留原文顺序 |
| 标题 | 文章标题 + h1–h6 层级写入 `section_path`，不混入正文；Embedding 和精排包含标题路径 |
| 短块 | 前块少于 100 token，可与同标题路径的下一块合并；代码后的简短解释也可合并；合并后最多 500 token |
| 完整段落 | 在 800 token 内保持完整，即使超过 500 token，也不会为了凑固定长度切开 |
| 超长段落 | 优先句末/换行；没有合适边界时按 Unicode 码点切分，避免破坏 emoji 等字符 |
| 代码 | 保留换行、缩进、HTML 实体解码后的正文与语言；使用安全 Markdown 围栏，超长代码按行分块，每块保留围栏；单行过长才按预算切分 |
| 列表 | 保留有序/无序层级，超长时按行分块 |
| 表格 | 转为 Markdown 行；有 th 表头时每块重复表头；超长表格按行分块，单行超预算时采用有界切分，不保证跨块仍为完整表格行 |
| 无关节点 | 移除 script/style/noscript/iframe/svg/canvas 及 hidden/aria-hidden=true 节点；不索引图片像素 |
| 单篇上限 | 512 块；超过上限或标题/表头占满预算时明确失败，不静默截断正文 |

预算计入标题路径和代码围栏。token 使用本地 CL100K tokenizer，是对当前智谱 Embedding 输入的近似预算，不能等同于供应商实际计费 token。这里采用结构分块，没有额外 LLM 判断语义，也没有 Parent Expander 或相邻块自动扩展。

## 身份、融合与证据

- `source_hash = SHA-256(原始 HTML UTF-8)`，与最终证据校验保持一致。
- `chunker_version = html-dom-v1`；`chunk_id = article_id + '_' + chunker_version + '_' + source_hash + '_' + chunk_index`，同时作为 ES 文档 `_id`。
- KNN 和 BM25 使用相同的版本、标签、分类、作者、发布时间过滤。BM25 搜索 `chunk_content^3 / section_path / title^0.5`；KNN 使用原始相似度排序，不先混入热度。
- 每个排名列表内先去重，再按 `1 / (60 + rank)` 加分。相同块跨路累计，文章内不同块保留独立身份；同 ID 对应不同内容时报告可重试冲突。
- MySQL 回查仅接受 `status=1 AND deleted=0`；核对正文 Hash、标题、作者、分类、发布时间和当前关联标签。块正文与 chunk_index 原样保留，不能再用整篇正文覆盖。
- 粗排默认 20 块；精排最终最多 5 块、每篇最多 3 块。API 精排最多请求 15 个排名，再做文章多样性筛选；基础设施失败使用同样限额的粗排降级，相关性判定全部不达标则返回空证据。
- 引用含 `chunkId/chunkIndex/sourceHash/sectionPath`；前端 excerpt 预览最多 1200 字符，模型上下文包含完整的有界块正文。任务引用前缀在构建时加入，避免重新用 excerpt 拼上下文而截断代码。文章卡片按 article_id 去重。

## 写入、更新与重建

文章发布/编辑/删除的索引消息由 `ArticleIndexPublisher` 在事务 afterCommit 发送，回滚不会发消息，避免消费者读取尚未提交的正文或标签。转为草稿/下架的编辑也发送消息，以清理不再公开的块。

同一篇文章使用 MySQL 连接级 `GET_LOCK('easyjob_rag_' + article_id, 10)` 串行建索引，消费和批量重建共用此锁。锁连接在 Embedding 期间持有，业务读库还需额外连接，因此连接池必须能提供至少两个连接。

每条队列消息都重新读取当前业务状态，延迟到达的删除消息不能误删已经重新发布的文章。Embedding 每批 16 块，校验数量、2048 维和有限数值；全部向量生成后执行 Bulk（等待 refresh）。Bulk 部分失败会抛错供 Rabbit 重试。写入后重新读取文章与标签，内容或相关元数据变化时重试；确认未变化才清理不属于当前批次的旧块。delete-by-query 超时或部分失败也会抛错。

这不是跨 MySQL/ES 的事务，也不是完整的索引 Outbox 或 alias 原子发布：提交后发送消息仍有进程退出/投递失败窗口；失败 Bulk 可能留下部分新块，但不会先删除完整旧版本；查询时会剔除不匹配当前业务源的旧块。投递失败或达到现有 Rabbit 重试上限后仍可能需要人工重投消息或重建。

### 现有文章必须重建

新查询明确过滤 `html-dom-v1`，旧块不会作为兼容结果混入，因此配套上线前应先完成公开文章重建。启动时只增补 ES mapping，不自动调用 Embedding 重建所有文章。

显式启动 Java 的单次重建：

```powershell
java -jar target/easyjob-0.0.1-SNAPSHOT.jar --rag.reindex.enabled=true
```

使用实际构建产物和原有运行配置。也可以临时设置 Spring 环境变量 `RAG_REINDEX_ENABLED=true`。重建按 article_id 升序每页读取 100 篇公开文章，逐篇读取最新源；失败时停止并报告，重新启动会从头幂等重建。完成后关闭此配置，后续发布/编辑由原有队列更新。Java/Python 应同时发布，正文更新期间可能出现暂时无可用证据。

本次仅完成代码和离线验证，没有连接业务 MySQL/ES，也没有触发真实 Embedding 或执行重建。RAG 无新增 MySQL 表迁移。

## 验证

149 个 Python 离线用例通过，25 个 Java 指定单元用例通过，7 个前端流式协议用例通过；覆盖 DOM 段落、标题及同名章节边界、Unicode、代码围栏和缩进、长表格、嵌套列表、稳定块 ID、同块跨路融合、过滤下推、旧版本剔除、SQL 来源校验、完整上下文、降级多样性、并发源变更、延迟删除、锁失败、Bulk 失败传播与事务提交/回滚投递。

真实部署仍需验证 ES IK mapping、MySQL 命名锁/连接池、队列重试、Embedding 输入限制及真实检索质量。离线测试不能证明重建耗时或实际召回提升幅度。
