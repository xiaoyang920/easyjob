# 技术文章结构化分片：HTML/Markdown、Token 参数与检索闭环

> 文档状态：**目标方案已整理，尚未实现**  
> 最后更新：2026-08-21  
> 适用范围：EasyJob 技术博客文章的存储、解析、分片、Embedding、ES 索引和 RAG 召回  
> 当前实现基线：`DocumentChunkService` + `ArticleVectorListener` + `article_vectors`  
> RAG 总路线：`20-rag-optimization.md`

本文档保存本轮关于 HTML/Markdown 正文、结构感知分片、Token 参数、条件式 overlap 和检索优化的统一方案，供后续实施。文中的 `480/700/64` 是首轮评测基线，不是已经证明的最优值。

## 1. 当前真实链路

### 1.1 正文存储格式

当前主创作页使用 wangEditor：

```vue
<Editor v-model="valueHtml" />
```

保存和发布时提交：

```typescript
content: valueHtml.value
```

所以当前主链实际为：

```text
wangEditor
→ HTML 字符串
→ ArticleCreateDTO.content
→ Article.content
→ MySQL article_info.content
→ ArticleDetail.vue 使用 v-html 渲染
```

`ArticleCreateDTO.contentType` 虽然预留 `1=富文本、2=Markdown`，但创建页没有真正的 raw Markdown 编辑、提交和渲染闭环。页面提示的 Markdown 快捷输入只是 wangEditor 将 `#`、代码围栏等快捷语法转换为富文本节点，最终保存的仍是 HTML。

### 1.2 当前分片方式

发布文章后：

```text
ArticleServiceImpl
→ RabbitMQ PUBLISH/UPDATE
→ ArticleVectorListener
→ DocumentChunkService.chunk()
→ EsVectorStore.saveChunks()
→ article_vectors
```

`DocumentChunkService` 当前执行：

```text
Jsoup.parse(html).text()
→ 所有空白和换行压成一个空格
→ Spring AI TokenTextSplitter
```

硬编码参数：

```text
chunkSize             = 500 token
minChunkSizeChars     = 100 characters
minChunkLengthToEmbed = 50 characters
maxNumChunks          = 50
keepSeparator         = true
```

当前缺陷：

- HTML 标题层级丢失；
- 段落、列表、引用边界丢失；
- 代码换行和缩进丢失；
- 表头与单元格关系丢失；
- YAML 中 `chunk-overlap=100` 未绑定，实际没有 overlap；
- 标题和 heading path 不参与 Embedding；
- 最多 50 块但没有完整性校验；
- 每块逐次调用 Embedding，只有 ES 写入是 bulk；
- UPDATE 先删除旧块，再解析和写新块，失败时会留下索引空窗；
- PUBLISH 不清理旧尾块，内容变短后可能残留；
- 当前 Hybrid/RRF/Rerank 目标链存在接口契约错误，不能视为已打通。

## 2. 目标原则

1. **源格式明确**：HTML 和 Markdown 不能靠内容猜测。
2. **结构优先**：先解析结构，再控制 Token；禁止先压成纯文本。
3. **统一中间模型**：HTML DOM 与 Markdown AST 最终转换成同一组 Block。
4. **自然边界优先**：标题、段落、代码、表格是一级边界。
5. **条件式 overlap**：只有语义单元被迫切开时才重叠。
6. **检索文本与展示文本分离**：标题路径可参与向量化，但不污染原正文。
7. **索引可重建、可切换、可回滚**：使用版本化索引和 alias。
8. **参数由评测决定**：不能把云平台默认值当作 EasyJob 的最终答案。
9. **解析失败必须暴露**：禁止静默退化成整篇原始 HTML 或 Markdown。

## 3. HTML 与 Markdown 的存储方案

### 3.1 当前 HTML 文章

当前 HTML 文章继续使用：

```text
content_type = HTML
source_content = wangEditor 输出的 HTML
```

展示前必须执行服务端或可信渲染层的 HTML 白名单清洗。当前详情页直接 `v-html="article.content"`，如果入库链路没有可靠消毒，会形成存储型 XSS 风险。

### 3.2 真正支持 Markdown 时

如果未来增加独立 Markdown 编辑器、`.md` 导入或源码导出，推荐保存：

```text
content_type   = MARKDOWN
source_content = 原始 Markdown
rendered_html  = Markdown 解析并安全清洗后的 HTML
```

职责：

- `source_content`：重新编辑、导入导出、RAG AST 解析的事实源；
- `rendered_html`：详情页展示，避免每次读取重复解析；
- `content_type`：选择编辑器、解析器和渲染器。

如果只需要 wangEditor 的 Markdown 快捷输入，则没有必要额外保存 raw Markdown；最终仍统一保存 HTML。

### 3.3 RAG 不依赖展示 HTML

```text
HTML source     → Jsoup DOM Parser     ┐
                                      ├→ Unified Block Model → Chunk Assembler
Markdown source → Markdown AST Parser ┘
```

Markdown 不应先转 HTML 再 `.text()`，更不能用正则解析标题和代码围栏。AST 能直接保留标题、列表、代码语言、表格和引用关系。

## 4. 统一 Block 模型

建议的逻辑模型：

```java
class DocumentBlock {
    BlockType type;
    String text;
    int headingLevel;
    List<String> headingPath;
    String language;
    Map<String, Object> attributes;
    int sourceStart;
    int sourceEnd;
}
```

目标 BlockType：

```text
HEADING
PARAGRAPH
LIST
LIST_ITEM
BLOCKQUOTE
CODE
TABLE
IMAGE_CAPTION
DIVIDER
```

`heading_path` 示例：

```html
<h1>Spring事务</h1>
<h2>传播机制</h2>
<h3>REQUIRED</h3>
<p>……</p>
```

对应正文 Block：

```json
{
  "headingPath": ["Spring事务", "传播机制", "REQUIRED"],
  "type": "PARAGRAPH",
  "text": "……"
}
```

## 5. 解析规则

### 5.1 HTML DOM

使用 Jsoup 遍历 DOM，而不是直接 `.text()`：

- `h1～h6`：更新标题栈；
- `p`：正文段落；
- `ul/ol/li`：保留列表与项目关系；
- `blockquote`：独立引用块；
- `pre/code`：保留换行、缩进和 language；
- `table`：保留 caption、表头和行；
- `img`：只保留可信 alt/caption，图片理解属于后续多模态能力；
- `script/style/iframe`：不进入正文；
- 未知容器：按确定性规则递归读取子节点，并记录解析告警。

### 5.2 Markdown AST

Markdown 解析器至少识别：

- ATX/Setext heading；
- paragraph；
- ordered/unordered list；
- fenced/indented code block 和 language；
- blockquote；
- table 扩展；
- link 与 image alt；
- thematic break。

解析器库、GFM 扩展范围和 HTML-in-Markdown 策略需要在编码前定稿，不能用正则表达式替代 AST。

### 5.3 解析验证与失败处理

Jsoup 会修复许多不规范 HTML，因此“没有异常”不代表结构提取完整。目标验证：

1. 源内容非空；
2. 可见文本非空；
3. Block 集合非空；
4. Block 合并后的规范化文本与基础可见文本覆盖率一致；
5. 代码、表格等受保护结构没有无故丢失；
6. 每个 Block 和 Chunk 都满足 Token 上限；
7. 总 Chunk 数没有超限或静默截断。

结构提取失败时：

```text
抛出明确索引异常
→ RabbitMQ 按可重试策略处理
→ 最终进入持久 DLQ/失败任务
→ 记录 article_id、content_hash、parser_version 和原因
→ 修复后重放
```

禁止捕获异常后把原始 HTML/Markdown 整篇作为一个 Chunk 写入。更新文章时也不能先删除旧向量；应先完成新内容的解析、校验和 Embedding，再切换或覆盖索引版本。

## 6. Chunk 组装算法

### 6.1 标题路径建立章节

标题栈按 level 更新：

```text
遇到 h1 → 清空后加入 h1
遇到 h2 → 保留 h1，替换/加入 h2
遇到 h3 → 保留 h1/h2，替换/加入 h3
```

不同完整 `heading_path` 表示不同章节。不能因为两个标题都是 h2 就认为它们属于同一语义单元。

### 6.2 段落聚合

同一标题路径下，将连续小段落聚合：

```text
段落1 220 token
段落2 200 token
→ 合并为一个约420 token Chunk
```

组装规则：

1. 保持 Block 原子性；
2. 达到软下限后允许结算；
3. 尽量接近 target；
4. 加入下一 Block 会超过 hard max 时，先结算当前 Chunk；
5. 小于最小独立大小的普通段落优先与同章节相邻段合并；
6. 完整但较短的独立章节可以单独成块，不为凑数跨标题强行合并；
7. 单个 Block 超过 hard max 时进入该类型专用拆分器。

### 6.3 条件式 overlap

判断依据是“完整语义单元是否被迫拆开”，不是“相邻 Chunk 是否处于同一标题层级”。

| 场景 | overlap 策略 |
|---|---|
| h2 切换到另一个 h2 | 不重叠 |
| heading_path 不同 | 不重叠 |
| 同章节、完整段落边界切分 | 默认不重叠 |
| 单个超长段落被拆成多块 | 使用约 64 token overlap |
| 超长代码块被迫拆分 | 使用约 48 token 上下文或重复签名 |
| 超长表格 | 不做普通 overlap，重复表头 |

标题路径会重复进入每个 Chunk 的检索前缀，它承担章节上下文，不需要复制上一章节正文。

### 6.4 普通正文的递归边界

单个长正文 Block 的拆分优先级：

```text
完整段落
→ 中文/英文句末（。！？.!?）
→ 分号
→ 其他安全边界
→ 最后才按 Token 硬切
```

不得在 Unicode 组合字符、URL、代码 token 或 HTML entity 中间切断。

## 7. 初始 Token 参数

### 7.1 EasyJob 首轮基线

```text
targetTokens          = 480
softMinTokens         = 320
softMaxTokens         = 560
hardMaxTokens         = 700
minStandaloneTokens   = 120
forcedSplitOverlap    = 64
codeSplitOverlap      = 48
maxChunksPerArticle   = 200（超限必须失败或告警，不得截断）
```

含义：

- 480 是组装目标，不要求每块精确等长；
- 320～560 是普通正文的期望范围；
- 700 是业务结构上限，不是 Embedding 模型最大输入；
- 64 只用于被迫拆分的长正文，约为 target 的 13%；
- 标题路径和检索前缀也占 Token，计数时必须包含；
- 参数必须配置化并记录 `tokenizer_name/chunker_version`。

### 7.2 参数依据

公开资料显示不存在统一最优值：

- [AWS Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html) 的托管知识库默认固定分片为 300 token、20% overlap。
- [Azure AI Search](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents) 建议从 512 token、25% overlap 开始，同时指出结构化内容可以减少重叠。
- [Google Vertex AI RAG](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/fine-tune-rag-transformations) 的默认值为 1024 token、256 token overlap。
- [Anthropic Contextual Retrieval](https://www.anthropic.com/research/contextual-retrieval) 的成本与实验说明使用过 800-token Chunk，并为每块增加约 50～100 token 的上下文；实验覆盖代码、论文等多个领域。
- [NVIDIA 分片实验](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/) 测试 128/256/512/1024/2048 token；事实型查询多在 256～512 表现较好，复杂分析常受益于 1024，2048 通常出现收益下降；其 FinanceBench 实验中 15% overlap 优于测试的 10% 和 20%。
- [Chroma 分片评测](https://research.trychroma.com/evaluating-chunking) 显示分片策略可显著影响召回；其数据中 200-token 递归分片具有较好的综合 Token 效率，400-token 语义聚类获得较高召回，而 800/400 的大重叠配置冗余明显。
- [长文档检索研究](https://arxiv.org/abs/2505.21700) 指出简短事实问题可能偏好 64～128 token，而需要广泛上下文的长文问题可能偏好 512～1024 token。

因此，480 只是结合中文技术文章、事实问答和原理分析后的折中起点。最终参数必须由 EasyJob 自有数据验证。

> 外部资料内容均已重新表述，未逐字复刻原文。

### 7.3 Token 计数器

Token 不是字符数。当前 Spring AI `TokenTextSplitter` 的估算方式不一定与智谱 `embedding-3` 服务端 tokenizer 完全一致。

目标实现：

1. 优先使用 Embedding 模型官方 tokenizer；
2. 官方未提供时，封装统一 `TokenCounter` 做近似计数；
3. 为标题前缀和 tokenizer 偏差预留安全空间；
4. 启动时验证向量维度和模型配置；
5. 索引记录估算 token_count；
6. 监控 Embedding 输入超限并 Fail-Fast，不能截断后继续。

## 8. 代码、表格与特殊结构

### 8.1 代码块

- 不超过 hard max：尽量整块保存；
- 超过 hard max：优先按类、方法、函数或空行边界拆分；
- 仍过长：按行安全拆分，不能在一行 token 中间切；
- 每个子块重复 language、heading path 和必要的类/方法签名；
- 展示内容保留原始缩进；
- 代码 overlap 约 48 token，仅用于被迫拆分。

未来如引入 Java/Python AST，只负责提高代码边界质量，不改变统一 Block/Chunk 契约。

### 8.2 表格

- 能放入 hard max：表格整体保存；
- 过长：按“表头 + 8～12 行”组块，实际仍以 token 上限为准；
- 每个后续块重复 caption 和表头；
- 不拆分一行的业务语义；
- 超大单元格超过 hard max 时必须采用明确规则或拒绝索引，不能静默截断。

### 8.3 列表与引用

- 短列表整体保存；
- 长列表按完整 list item 拆分；
- 子块重复列表所属 heading path；
- 引用和解释段尽量同块，超过上限再按段落拆分。

## 9. 检索文本与展示文本

每个 Chunk 分开保存：

```text
chunk_content：原始可展示正文
embedding_text：只在生成向量时构造
```

建议 Embedding 输入：

```text
文章标题：Spring事务详解
章节路径：事务传播机制 > REQUIRED
内容类型：正文

REQUIRED表示当前存在事务时加入该事务……
```

即：

```text
embedding_text = article_title + heading_path + block_context + chunk_content
```

标题路径前缀建议限制在约 80 token 内。标签可作为 ES metadata 和 BM25 字段；是否加入向量文本必须通过评测，不能默认堆入所有元数据。

Reranker 和最终引用应保留原始 `chunk_content`，并单独展示标题与 heading path。

## 10. 目标 Chunk 与索引字段

在现有字段基础上，目标至少增加：

| 字段 | 用途 |
|---|---|
| `content_type` | HTML / MARKDOWN |
| `heading_path` | 标题层级 |
| `block_types` | Chunk包含哪些结构类型 |
| `language` | 代码语言 |
| `token_count` | 实际估算 Token |
| `source_start/source_end` | 原文定位 |
| `prev_chunk_id/next_chunk_id` | 邻块扩展 |
| `category_id` | 分类过滤 |
| `publish_time/update_time` | 时间过滤和新鲜度 |
| `status/is_deleted/visibility` | 权限与生命周期 |
| `article_version` | 防止旧事件覆盖新版本 |
| `source_hash` | 幂等与变更检测 |
| `chunker_version` | 分片算法版本 |
| `parser_version` | 解析器版本 |

`heading_path` 应同时提供适合精确过滤和全文检索的映射；字段最终 mapping 在实施时一次定稿。

## 11. Chunk ID、更新与失败原子性

当前 `_id={articleId}_{chunkIndex}` 对重复投递基本幂等，但缺少内容版本。目标规则：

1. 消息携带 `article_version/source_hash`；
2. 消费者重新查询 MySQL 当前状态和版本；
3. 旧版本事件不得覆盖新版本；
4. 先完成解析、分片、全部 Embedding；
5. bulk 写入后检查每个 item；
6. 新版本完整成功后再清理旧尾块或切换有效版本；
7. DELETE/UNPUBLISH 必须传播失败，不能吞异常后 ack；
8. 状态改为草稿、下架、删除或可见性变化时同步更新/删除全文和向量索引；
9. 通过 Outbox、DLQ 和周期对账保证最终一致性。

禁止继续使用“UPDATE 先 delete-by-query，再开始 Embedding”的流程。

## 12. Chunk 级检索闭环

### 12.1 同粒度 Hybrid

目标是在同一个 Chunk 粒度执行：

```text
KNN：content_vector
BM25：title^3 + heading_path^2 + tags^2 + chunk_content
```

两路都以同一个 `chunk_id` 做融合，避免当前“向量返回 Chunk、关键词返回整篇 Article”导致 RRF key 不一致。

### 12.2 推荐流水线

```text
Query Rewrite（2～3条语义查询 + 关键词）
→ ACL/状态/分类/时间前置 Filter
→ 每路 KNN Top30
→ 每路 BM25 Top30
→ 手写 RRF（K=60）保留约30～40块
→ Reranker
→ 每篇文章最多保留约2个核心非重复块
→ 对最终核心块补充 ±1 邻块
→ 合并连续 Chunk
→ Citation + Prompt
```

具体数量必须通过评测调整。当前 `COARSE_TOP_K=5` 过早收窄，不适合作为宽召回后精排。

### 12.3 邻块扩展

邻块扩展放在 Reranker 选出核心证据之后，不能对所有粗候选无条件扩展：

```text
命中 chunk_5
→ 验证同 article/version/权限
→ 按需要获取 chunk_4、chunk_6
→ 去重并按 chunk_index 合并
```

标题切换或版本不一致时不跨边界扩展。相邻块是上下文窗口，不参与替代核心块的相关性分数。

### 12.4 去重与多样性

- 先按 `chunk_id` 融合；
- 合并同一文章连续块；
- 限制单篇文章占据候选数量；
- 高度相似时可增加 MMR，初始 `lambda=0.7` 仅作为实验值；
- 热度不得占语义分数 30%，建议只在 Rerank 后以小权重处理并统一 Java/Python 公式。

## 13. 评测方案

### 13.1 数据集

建立 100～200 条 EasyJob 技术博客标注问题，覆盖：

- 精确事实；
- 框架原理；
- 错误排查；
- 代码解释；
- 配置表格；
- 跨段关系；
- 中文、英文及混合内容；
- HTML/Markdown；
- 嵌套标题；
- 长代码和长表格；
- 私密、下架、删除文章不得召回。

### 13.2 三组首轮参数

| 组 | target | hard max | forced overlap | 预期场景 |
|---|---:|---:|---:|---|
| A 细粒度 | 320 | 512 | 48 | 短事实、错误码、配置项 |
| B 平衡型 | 480 | 700 | 64 | EasyJob 默认候选 |
| C 上下文型 | 768 | 1024 | 96 | 原理分析、跨段推理 |

结构完整的 Chunk 不因实验组不同而强行机械重叠。

### 13.3 指标

```text
Chunk Recall@20
MRR / nDCG@10
Rerank Recall@8
Context Precision / Context Recall
Faithfulness
Citation Precision
代码块完整率
表格行与表头完整率
同文章重复率
无结果率
平均注入 Token
索引体积
Embedding 成本
p50/p95 检索延迟
索引新鲜度
```

必须同时比较当前 `Jsoup.text + 500 Token` baseline，才能证明结构化分片确实改善结果。

## 14. 索引迁移

不能原地依赖 `initIndex()` 修改 mapping，因为索引存在时会直接跳过创建。目标迁移：

```text
创建 article_vectors_v2
→ 配置 read/write alias
→ 从 article_info 只回灌当前允许索引的文章
→ 使用新 Parser/Chunker/Embedding
→ 校验向量维度、Chunk数量、文本覆盖率、权限字段和版本
→ shadow 查询对比旧索引
→ 原子切换 read alias
→ 保留旧索引回滚窗口
```

发布和回灌并发期间必须使用 Outbox/版本号/增量补偿，避免切换后遗漏更新。

## 15. 分阶段实施顺序

### Phase 0：修正现有正确性

- 分片参数配置化，删除未生效的 YAML 假配置；
- 修复 PUBLISH/UPDATE/UNPUBLISH/DELETE 生命周期；
- Embedding 改为受限批处理；
- bulk 检查 item 级错误；
- 删除操作不再吞异常；
- 修通 Python QueryRewrite/Filter/Normalization/Citation 契约。

### Phase 1：统一 Block 与结构化分片

- 实现 HTML DOM Parser；
- 定义统一 Block/Chunk DTO；
- 实现标题栈和普通正文组装器；
- 实现条件式 overlap；
- 实现代码、表格、列表专用策略；
- 加入 parser/chunker version 和覆盖率校验。

### Phase 2：Markdown 完整闭环

仅在确认需要真正 Markdown 编辑时实施：

- 增加 raw Markdown 编辑器/导入；
- 明确 source_content/rendered_html 数据模型；
- Markdown AST Parser；
- 安全渲染与 XSS 白名单；
- HTML/Markdown 统一进入 Block 组装器。

### Phase 3：索引与召回升级

- 建立 `article_vectors_v2`；
- 补全过滤、权限、版本和邻接字段；
- 同一 Chunk 粒度 KNN + BM25；
- 手写 RRF、Reranker、文章多样性和邻块扩展；
- Citation 使用原文定位。

### Phase 4：回灌、评测与切换

- 构建离线标注集；
- 运行 A/B 参数矩阵；
- shadow 查询；
- alias 切换和回滚演练；
- 建立索引对账与质量看板。

## 16. 验收标准

实施完成至少满足：

- HTML 标题、段落、列表、代码和表格结构可追踪；
- 真正的 Markdown 文章由 AST 解析，不依赖正则；
- 每个 Chunk 都有 heading path、token count、version 和 source hash；
- 普通自然边界没有无意义 overlap；
- 被迫拆分的长段落、代码和表格保持必要上下文；
- 不存在静默截断、空 Chunk 或超过 hard max 的 Chunk；
- 解析失败不会写入污染索引；
- 更新失败不会先删除有效索引且错误可观测；
- KNN 和 BM25 使用相同 chunk_id 融合；
- Reranker 后邻块扩展不跨文章、版本、权限或标题边界；
- 私密、草稿、下架、删除文章不会进入无权用户候选；
- 新方案相对 baseline 的召回、引用正确率和成本有可复现实验报告。

## 17. 实施前必须确认的事项

1. 是否真的需要 raw Markdown 编辑/导出，还是保留 wangEditor HTML 即可。
2. 数据库采用 `content/source_content/rendered_html` 哪种最终字段设计。
3. Markdown AST 库、GFM扩展和 HTML-in-Markdown 策略。
4. HTML 白名单和现有历史内容的安全清洗方案。
5. 与智谱 embedding-3 对齐的 TokenCounter。
6. 超大代码块、超大表格单元格和异常 DOM 的最终拒绝/拆分规则。
7. Chunk ID 与 article_version 的最终组合方式。
8. 新索引、alias 名称、双写周期和旧索引保留期。
9. 480/700/64 是否通过 EasyJob 标注集验证。
10. KNN/BM25/RRF/Rerank 的候选数量与 Token Budget。

## 18. 相关文档

- `docs/learning/agent/20-rag-optimization.md`：RAG Query Rewrite、Filter、RRF、Rerank、Citation 总路线。
- `docs/learning/agent/21-main-agent-subagent-staged-architecture.md`：Search Subagent 与权限上下文。
- `src/main/java/com/easyjob/agent/component/DocumentChunkService.java`：当前固定 Token 分片实现。
- `src/main/java/com/easyjob/listener/ArticleVectorListener.java`：当前向量消息消费入口。
- `src/main/java/com/easyjob/agent/component/EsVectorStore.java`：当前 Embedding 与 ES 写入。
- `frontend/src/views/CreateArticle.vue`：当前 wangEditor HTML 来源。
- `frontend/src/views/ArticleDetail.vue`：当前 HTML 展示入口。
