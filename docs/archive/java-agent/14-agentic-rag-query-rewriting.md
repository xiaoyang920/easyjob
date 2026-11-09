> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# 14 - Agentic RAG：Query Rewriting + Two-Stage Retrieval with Reranker

## 一、背景与问题

### 1.1 当前架构回顾

```
START → PlannerNode → DispatcherNode → SynthesizerNode → END
                          ├── SearchWorkerNode（并行）
                          ├── AnalysisWorkerNode
                          ├── WritingWorkerNode
                          └── ChatWorkerNode
```

当前 `SearchWorkerNode` 的检索流程：
```
taskInput（Planner定制的任务描述）
    ↓
retrieveRagContext(taskInput)  →  EsVectorStore.search(query, 5, 0.7f)
    ↓
ChatClient + ArticleTool/BochaSearchTool（LLM自主决定调哪个Tool）
    ↓
返回结果（一次性，无反馈）
```

### 1.2 存在的问题

| 问题 | 具体表现 | 影响 |
|------|----------|------|
| **无 Query 重写** | Planner 的 taskDescription 直接作为检索 query，可能包含"搜索Java并发相关的文章"这种指令性文本，而非检索友好的关键词 | 向量检索召回质量低 |
| **无指代消解** | 多轮对话中"帮我搜下那个"、"第一篇详细说说"，Planner 虽然尝试解析但不一定准确 | 检索 query 模糊 |
| **无检索质量评估** | 搜一次就完事，不管召回的文档是否真的相关 | 可能基于无关文档生成回答 |
| **无重试机制** | 检索失败或结果为空时直接返回空 | 用户体验差 |
| **单一检索策略** | RAG 只用向量搜索，Tool 调用由 LLM 自主决定 | 无法根据 query 特征选择最优检索策略 |

### 1.3 为什么 Planner 的 taskDescription 不能直接用于检索？

Planner 带着历史消息做了指代消解，也把任务描述优化过了，但它的优化目标是"任务指令清晰"——输出的是给 Worker 看的自然语言指令（如"搜索Java并发相关的文章"）。这对 Worker 理解任务来说足够了，但对向量检索来说不是最优的 query：

1. **指令性噪声**：Planner 的 task 天然是指令格式，"搜索"、"相关的文章"这些词会干扰向量检索的语义匹配
2. **单一视角**：一个 task 只有一个表述角度，无法通过多角度扩展提高召回覆盖面
3. **无策略区分**：Planner 只输出一个 task 字符串，而语义搜索和关键词搜索需要不同形式的 query

因此需要在 Planner（理解意图）和实际检索（ES/向量搜索）之间加一层"翻译"，把人能看懂的指令转成搜索引擎能高效匹配的形式。

## 二、目标架构：Two-Stage Retrieval with Reranker

### 2.1 核心理念

业界主流的前沿做法是**两阶段检索（Two-Stage Retrieval）**：

- **第一阶段（粗检索）**：用向量搜索 + 关键词搜索广撒网，召回 20-30 个候选文档。速度快，但精度一般。
- **第二阶段（精排 Rerank）**：用专门的 Cross-Encoder Reranker 模型对候选文档重新打分排序，筛出 Top 5 最相关的。

```
Query → Rewrite → 粗检索（宽召回）→ Reranker 精排 → Top-K 送给 LLM
```

**为什么用 Reranker 而不是 LLM 做相关性评估？**

| | LLM Grade（旧方案） | Cross-Encoder Reranker（新方案） |
|---|---|---|
| 评分方式 | 调大模型做相关性判断，需要把所有文档内容发给 LLM | 专用小模型，query+doc 拼接做一次 forward pass |
| 成本 | 高（每次评分消耗大量 token，20个文档≈4000+ token） | 极低（Qwen3-Reranker-0.6B 每百万 token $0.01） |
| 延迟 | 高（LLM 推理 1-3s） | 低（200-500ms 处理 20-50 个文档） |
| 精度提升 | 取决于 LLM 能力和 prompt 质量 | 15-40%（专门训练的排序模型，比向量余弦相似度准得多） |
| 可靠性 | LLM 输出需要解析 JSON，可能格式错误 | 直接输出数值分数，无解析风险 |

参考来源：
- [Two-Stage Retrieval for Better Results (2026)](https://stackviv.ai/blog/retrieval-reranking-rag-systems)
- [The Most Accurate Reranker Models For RAG Pipelines In 2026](https://www.siliconflow.com/articles/en/most-accurate-reranker-for-rag-pipelines)
- [FlashRank: Two-Stage Retrieval with Marginal-Utility Reranking (arxiv 2026)](https://arxiv.org/html/2601.03258v1)
- [Cross-Encoder Reranking: The Low-Cost Fix for RAG Misses](https://blog.thegenairevolution.com/article/cross-encoder-reranking-the-low-cost-fix-for-rag-misses)
- [BGE Reranker: Cross-Encoder Reranking for Better RAG 2026](https://markaicode.com/bge-reranker-cross-encoder-reranking-rag/)
- [Spring AI RAG 官方文档 - RetrievalAugmentationAdvisor](https://docs.spring.io/spring-ai/reference/api/retrieval-augmented-generation.html)

### 2.2 升级后的 SearchWorkerNode 内部流程

```
taskInput + historyMessages
    ↓
┌─────────────────────────────────────────────┐
│           QueryRewriteStep（LLM，1次调用）   │
│  LLM 结合对话历史重写 query：                │
│  - 指代消解（"那个" → 具体内容）             │
│  - 去指令化（"搜索xxx文章" → "xxx"）         │
│  - 生成 2-3 个多角度子 query（Multi-Query）  │
│  - 提取关键词（用于 ES 全文搜索）            │
└─────────────────────────────────────────────┘
    ↓ rewrittenQueries + keywords
┌─────────────────────────────────────────────┐
│           RetrieveStep（粗检索，宽召回）      │
│  对每个 rewrittenQuery 执行混合检索：        │
│  - EsVectorStore 语义搜索（向量 KNN）        │
│  - EsComponent 关键词搜索（ES 全文搜索）     │
│  - BochaSearchTool 联网搜索（按需）          │
│  合并去重所有结果（20-30 个候选）             │
└─────────────────────────────────────────────┘
    ↓ candidateDocuments: List<ScoredDocument>
┌─────────────────────────────────────────────┐
│           RerankStep（精排，零 LLM 调用）     │
│  Cross-Encoder Reranker 模型精排：           │
│  - 用原始 taskInput 与每个候选文档配对打分    │
│  - 按相关性分数降序排列                      │
│  - 取 Top-K（默认5）+ 分数阈值过滤           │
└─────────────────────────────────────────────┘
    ↓ topRelevantDocs（5个最相关文档）
    ├─ 有相关文档 → 构建 RAG context → LLM 生成回答
    └─ 无相关文档 → RetryStep（换角度重写，最多重试2次）
```

**与旧方案的关键区别**：
- Rerank 环节不调 LLM，用专用小模型（如 Qwen3-Reranker / BGE-Reranker），成本和延迟降一个数量级
- 粗检索阶段放宽阈值多召回，精排阶段严格筛选，"宽进严出"
- 最终送给 LLM 的文档数量可控（Top-5），token 消耗稳定

## 三、详细设计

### 3.1 新增类与职责

```
agent/
├── service/
│   └── QueryRewriteService.java      # Query 重写服务（LLM，1次调用）
│   └── RerankerService.java          # Reranker 精排服务（Cross-Encoder 模型，非 LLM）
├── graph/node/
│   └── SearchWorkerNode.java         # 改造：集成两阶段检索 + Reranker
├── model/
│   └── ScoredDocument.java           # 带分数的文档数据模型
```

### 3.2 Reranker 模型选型

2026 年主流 Reranker 模型对比：

| 模型 | 参数量 | 多语言 | 上下文长度 | 成本（SiliconFlow） | 适用场景 |
|------|--------|--------|-----------|---------------------|----------|
| **Qwen3-Reranker-0.6B** | 0.6B | 100+语言 | 32K | $0.01/M tokens | 轻量级，性价比最高 |
| **Qwen3-Reranker-4B** | 4B | 100+语言 | 32K | $0.02/M tokens | 精度与成本平衡，推荐生产环境 |
| **Qwen3-Reranker-8B** | 8B | 100+语言 | 32K | $0.04/M tokens | 最高精度，关键业务场景 |
| **BGE-Reranker-v2-m3** | ~0.6B | 多语言 | 8K | 开源自部署 | 自部署场景 |

**推荐**：本项目使用 **Qwen3-Reranker-0.6B** 或 **BGE-Reranker-v2-m3**。
- 平台文章以中文为主，0.6B 级别模型足够
- 文档摘要长度有限（200字以内），不需要长上下文
- 成本极低，可以对 20-30 个候选文档全量精排

### 3.3 QueryRewriteService - Query 重写服务（不变）

**职责**：接收原始 taskInput + 对话历史，输出优化后的检索 query 列表。

**重写策略**：
1. **Contextual Rewrite（上下文重写）**：结合对话历史解决指代消解，将模糊的 query 转为明确的检索语句
2. **Multi-Query Expansion（多查询扩展）**：将一个 query 从不同角度扩展为 2-3 个子 query，提高召回覆盖面
3. **Keyword Extraction（关键词提取）**：从指令性文本中提取纯检索关键词，用于 ES 全文搜索

```java
package com.easyjob.agent.service;

import com.easyjob.entity.AiMessage;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;

import java.util.ArrayList;
import java.util.List;

/**
 * Query 重写服务
 * 
 * 结合对话历史和用户意图，将原始 query 重写为检索友好的多个子 query。
 * 核心策略：指代消解 + 多角度扩展 + 关键词提取
 * 
 * 使用 Spring AI 的 Structured Output 功能，自动将 LLM 输出解析为 Java 对象。
 */
@Slf4j
public class QueryRewriteService {

    private final ChatClient rewriteClient;

    private static final String REWRITE_PROMPT = """
            你是一个查询重写专家。你的任务是将用户的原始查询优化为更适合信息检索的形式。
            
            【输入】
            - 原始查询（可能是 Planner 生成的任务描述，包含指令性文本）
            - 对话历史（用于理解上下文和指代）
            
            【重写规则】
            1. **指代消解**：如果查询中有"它"、"那个"、"上面的"、"第一篇"等指代词，
               根据对话历史替换为具体内容
            2. **去指令化**：去掉"搜索"、"帮我找"、"查一下"等指令性词汇，
               保留纯检索语义。例如"搜索Java并发相关的文章" → "Java并发编程"
            3. **多角度扩展**：从不同角度生成 2-3 个检索 query，覆盖更多相关文档
               例如"Spring Boot性能优化" → ["Spring Boot性能调优", "SpringBoot响应速度提升", "Spring Boot JVM参数配置"]
            4. **关键词提取**：额外提取 1-2 个核心关键词，用于精确匹配搜索
            """;

    public QueryRewriteService(ChatClient rewriteClient) {
        this.rewriteClient = rewriteClient;
    }

    /**
     * 重写 query
     *
     * @param taskInput       Planner 生成的任务描述
     * @param historyMessages 对话历史（直接使用 AiConversationService.getContext() 返回的 List<AiMessage>）
     * @return 重写结果，包含语义检索 query 列表和关键词列表
     */
    public RewriteResult rewrite(String taskInput, List<AiMessage> historyMessages) {
        List<Message> messages = new ArrayList<>();
        if (historyMessages != null && !historyMessages.isEmpty()) {
            // 只取最近3轮对话作为重写上下文（避免 token 浪费）
            int start = Math.max(0, historyMessages.size() - 6);
            for (int i = start; i < historyMessages.size(); i++) {
                AiMessage msg = historyMessages.get(i);
                if ("user".equals(msg.getRole())) {
                    messages.add(new UserMessage(msg.getContent()));
                } else if ("assistant".equals(msg.getRole())) {
                    messages.add(new AssistantMessage(msg.getContent()));
                }
            }
        }
        messages.add(new UserMessage(REWRITE_PROMPT + "\n\n原始查询：" + taskInput));

        try {
            // 使用 Spring AI 的 entity() 方法，自动将 LLM 输出解析为 Java 对象
            // Spring AI 会：
            // 1. 根据 RewriteResult 类自动生成 JSON Schema
            // 2. 将 Schema 注入 prompt，引导 LLM 输出符合格式的 JSON
            // 3. 自动将 LLM 返回的 JSON 反序列化为 RewriteResult 对象
            RewriteResult result = rewriteClient.prompt()
                    .messages(messages)
                    .call()
                    .entity(RewriteResult.class);

            // 校验结果，确保 semanticQueries 不为空
            if (result == null || result.semanticQueries() == null || result.semanticQueries().isEmpty()) {
                return RewriteResult.fallback(taskInput);
            }

            log.info("Query重写完成: 原始='{}', 语义queries={}, 关键词={}",
                    truncate(taskInput, 50), result.semanticQueries(), result.keywords());
            return result;
        } catch (Exception e) {
            log.error("Query重写失败，降级使用原始query", e);
            return RewriteResult.fallback(taskInput);
        }
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }

    /**
     * 重写结果数据类
     * 
     * Spring AI 的 entity() 方法会根据这个 record 自动生成 JSON Schema，
     * 引导 LLM 输出符合格式的 JSON，并自动反序列化为此对象。
     */
    public record RewriteResult(
            List<String> semanticQueries,  // 语义检索用的 query 列表
            List<String> keywords          // 关键词搜索用的关键词列表
    ) {
        public static RewriteResult fallback(String originalQuery) {
            return new RewriteResult(List.of(originalQuery), List.of());
        }
    }
}

### 3.4 RerankerService - Reranker 精排服务（核心新增，替代旧方案的 LLM Grade）

**职责**：使用 Cross-Encoder Reranker 模型对粗检索的候选文档进行精排，筛出最相关的 Top-K 文档。

**核心优势**：
- 不调 LLM，零 token 消耗（相对于大模型）
- Cross-Encoder 把 query 和 document 拼接在一起做 forward pass，能捕捉深层语义交互
- 比向量余弦相似度（Bi-Encoder）精度高 15-40%，因为 Bi-Encoder 是分别编码再算距离，丢失了 query-doc 之间的交叉注意力

**调用方式**：通过阿里云 DashScope Reranker API 调用，不依赖 Spring AI ChatModel。

```java
package com.easyjob.agent.service;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.easyjob.entity.DocumentChunk;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.*;

/**
 * Reranker 精排服务
 *
 * 使用阿里云 DashScope 的 Reranker 模型对候选文档进行相关性精排。
 * 替代旧方案中的 LLM Grade，成本降低 100 倍以上，延迟降低 5-10 倍。
 *
 * Cross-Encoder 原理：将 query 和 document 拼接为 "[query] [SEP] [document]"，
 * 通过 Transformer 的交叉注意力机制直接输出相关性分数（0-1），
 * 比 Bi-Encoder（分别编码再算余弦距离）能捕捉更深层的语义匹配关系。
 */
@Slf4j
@Service
public class RerankerService {

    /** DashScope Reranker API 地址 */
    private static final String API_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank";

    @Value("${spring.ai.dashscope.api-key}")
    private String apiKey;

    @Value("${reranker.model:qwen3-vl-rerank}")
    private String modelName;

    private HttpClient httpClient;

    /** 精排后保留的文档数量 */
    private static final int RERANK_TOP_K = 5;
    /** 相关性分数阈值（低于此分数的文档即使在 Top-K 内也会被过滤） */
    private static final double RELEVANCE_THRESHOLD = 0.3;

    @PostConstruct
    public void init() {
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    /**
     * 对候选文档进行精排
     *
     * @param query      原始查询（用 Planner 的 taskInput，而非重写后的 query）
     * @param documents  粗检索的候选文档列表（复用现有 DocumentChunk）
     * @return 精排后的 Top-K 相关文档，按相关性分数降序排列，分数已更新为 Reranker 分数
     */
    public List<DocumentChunk> rerank(String query, List<DocumentChunk> documents) {
        if (documents == null || documents.isEmpty()) {
            return List.of();
        }

        // 构建 DashScope Reranker API 请求体
        JSONObject requestBody = new JSONObject();
        requestBody.put("model", modelName);

        // DashScope 格式：input 包含 query 和 documents
        JSONObject input = new JSONObject();
        input.put("query", query);
        JSONArray docsArray = new JSONArray();
        for (DocumentChunk doc : documents) {
            // 拼接 title + content 作为文档文本
            String docText = doc.getTitle() + "\n" + truncate(doc.getContent(), 300);
            docsArray.add(docText);
        }
        input.put("documents", docsArray);
        requestBody.put("input", input);

        // DashScope 格式：parameters 包含 return_documents 和 top_n
        JSONObject parameters = new JSONObject();
        parameters.put("return_documents", false);
        parameters.put("top_n", Math.min(RERANK_TOP_K, documents.size()));
        requestBody.put("parameters", parameters);

        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(API_URL))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + apiKey)
                    .POST(HttpRequest.BodyPublishers.ofString(requestBody.toJSONString()))
                    .timeout(Duration.ofSeconds(15))
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() != 200) {
                log.error("Reranker API 调用失败, status={}, body={}", response.statusCode(), response.body());
                return fallbackByScore(documents);
            }

            return parseRerankResponse(response.body(), documents);
        } catch (Exception e) {
            log.error("Reranker API 调用异常，降级使用粗检索分数排序", e);
            return fallbackByScore(documents);
        }
    }

    /**
     * 解析 Reranker API 响应
     *
     * DashScope 响应格式：
     * {
     *   "output": {
     *     "results": [
     *       {"index": 3, "relevance_score": 0.92},
     *       {"index": 0, "relevance_score": 0.85},
     *       ...
     *     ]
     *   }
     * }
     */
    private List<DocumentChunk> parseRerankResponse(String responseBody, List<DocumentChunk> originalDocs) {
        try {
            JSONObject resp = JSON.parseObject(responseBody);
            JSONObject output = resp.getJSONObject("output");
            JSONArray results = output.getJSONArray("results");

            List<DocumentChunk> ranked = new ArrayList<>();
            for (int i = 0; i < results.size(); i++) {
                JSONObject item = results.getJSONObject(i);
                int index = item.getIntValue("index");
                double score = item.getDoubleValue("relevance_score");

                // 分数阈值过滤：即使在 Top-K 内，分数太低也不要
                if (score < RELEVANCE_THRESHOLD) {
                    continue;
                }

                if (index >= 0 && index < originalDocs.size()) {
                    DocumentChunk doc = originalDocs.get(index);
                    doc.setScore(score);  // 更新为 Reranker 分数
                    ranked.add(doc);
                }
            }

            log.info("Reranker精排完成: 候选文档={}, 精排后保留={}, 最高分={}, 最低分={}",
                    originalDocs.size(), ranked.size(),
                    ranked.isEmpty() ? "N/A" : String.format("%.3f", ranked.get(0).getScore()),
                    ranked.isEmpty() ? "N/A" : String.format("%.3f", ranked.get(ranked.size() - 1).getScore()));

            return ranked;
        } catch (Exception e) {
            log.error("Reranker响应解析失败，降级使用粗检索分数排序, 原始响应: {}", responseBody, e);
            return fallbackByScore(originalDocs);
        }
    }

    /**
     * 降级策略：Reranker 不可用时，按粗检索的原始分数排序取 Top-K
     */
    private List<DocumentChunk> fallbackByScore(List<DocumentChunk> documents) {
        log.warn("Reranker降级：使用粗检索原始分数排序");
        return documents.stream()
                .sorted(Comparator.comparingDouble(DocumentChunk::getScore).reversed())
                .limit(RERANK_TOP_K)
                .collect(Collectors.toList());
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}

### 3.5 改造 SearchWorkerNode - 集成两阶段检索 + Reranker

**核心改动**：将原来的"搜一次就完事"改为 rewrite → 粗检索（宽召回）→ reranker 精排 → retry 的两阶段检索流程。

**与旧方案的区别**：
- 旧方案的 Grade 环节调 LLM 做相关性判断（高 token 消耗），新方案用 Reranker 小模型精排（零 LLM 调用）
- 粗检索阶段放宽阈值（0.5f → 多召回），精排阶段严格筛选（Top-5 + 分数阈值）

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.service.QueryRewriteService;
import com.easyjob.agent.service.QueryRewriteService.RewriteResult;
import com.easyjob.agent.service.RerankerService;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.component.EsComponent;
import com.easyjob.entity.AiMessage;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.stereotype.Component;

import java.util.*;

@Slf4j
@Component
@RequiredArgsConstructor
public class SearchWorkerNode implements NodeAction {

    private final ChatModel chatModel;
    private final ArticleTool articleTool;
    private final BochaSearchTool bochaSearchTool;
    private final EsVectorStore esVectorStore;
    private final EsComponent esComponent;
    private final QueryRewriteService queryRewriteService;
    private final RerankerService rerankerService;

    /** 最大重试次数（含首次检索） */
    private static final int MAX_RETRIEVAL_ROUNDS = 3;
    /** 粗检索阶段：每个 semanticQuery 的 topK（放宽，多召回） */
    private static final int COARSE_TOP_K = 5;
    /** 粗检索阶段：相似度阈值（比旧方案的 0.7f 更宽松，让 Reranker 来精筛） */
    private static final float COARSE_SIMILARITY_THRESHOLD = 0.5f;

    private static final String SEARCH_SYSTEM_PROMPT = """
            你是一个信息检索助手，专门负责搜索和检索信息。
            
            【职责】
            - 根据任务指令，使用工具搜索平台文章或联网搜索实时信息
            - 返回结构化的搜索结果，包含标题、摘要、关键信息
            - 不要对搜索结果做过多分析，只负责检索和整理
            
            【当前日期】%s
            
            【输出要求】
            - 直接返回搜索结果，不要添加多余的开场白
            - 保持结果简洁、结构化
            - 不要把文章id露出来
            """;

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        Long conversationId = state.value("conversationId", 0L);
        String today = java.time.LocalDate.now().toString();

        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("search", state.value("userMessage", ""));
        List<AiMessage> historyMessages = state.value("historyMessages", List.of());

        // ========== 两阶段检索 + Reranker ==========
        List<DocumentChunk> relevantDocs = new ArrayList<>();

        for (int round = 0; round < MAX_RETRIEVAL_ROUNDS; round++) {
            log.info("SearchWorker 检索轮次 {}/{}", round + 1, MAX_RETRIEVAL_ROUNDS);

            // === Stage 1: Query Rewrite（LLM，1次调用） ===
            RewriteResult rewriteResult;
            if (round == 0) {
                rewriteResult = queryRewriteService.rewrite(taskInput, historyMessages);
            } else {
                String retryHint = "上一轮检索未找到相关结果，请换一个角度重写以下查询：" + taskInput;
                rewriteResult = queryRewriteService.rewrite(retryHint, historyMessages);
            }

            // === Stage 2a: 粗检索（宽召回，多策略混合） ===
            List<DocumentChunk> candidates = executeCoarseRetrieval(rewriteResult);

            if (candidates.isEmpty()) {
                log.info("SearchWorker 轮次 {} 粗检索结果为空，准备重试", round + 1);
                continue;
            }

            // === Stage 2b: Reranker 精排（Cross-Encoder，非 LLM） ===
            // 用原始 taskInput 做精排 query（不是重写后的 query），确保和用户原始意图对齐
            List<DocumentChunk> ranked = rerankerService.rerank(taskInput, candidates);

            if (!ranked.isEmpty()) {
                relevantDocs.addAll(ranked);
                log.info("SearchWorker 轮次 {} 精排后保留 {} 个相关文档，结束检索循环",
                        round + 1, ranked.size());
                break;
            }

            log.info("SearchWorker 轮次 {} 精排后无相关文档，准备重试", round + 1);
        }

        // ========== 生成最终回答 ==========
        String ragContext = buildRagContext(relevantDocs);
        String systemPrompt = SEARCH_SYSTEM_PROMPT.formatted(today);
        if (!ragContext.isEmpty()) {
            systemPrompt += "\n\n【RAG参考资料（已通过 Reranker 精排）】\n" + ragContext;
        }

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(systemPrompt)
                .build();

        String result = workerClient.prompt()
                .user(taskInput)
                .tools(articleTool, bochaSearchTool)
                .toolContext(Map.of("conversationId", conversationId))
                .call()
                .content();

        log.info("SearchWorker执行完成, 任务: '{}', 相关文档: {}, 结果长度: {}",
                truncate(taskInput, 50), relevantDocs.size(), result.length());

        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "search");
        workerResult.put("result", result);

        Map<String, Object> output = new HashMap<>();
        output.put("workerResults", workerResult);
        output.put("searchResult", result);
        return output;
    }

    /**
     * 粗检索：多策略混合，宽召回
     *
     * 两种检索策略互补：
     * 1. 语义搜索（EsVectorStore）：向量 KNN 召回，适合模糊/语义相似的 query
     * 2. 关键词搜索（EsComponent）：ES 全文搜索（multi_match on title+tags），适合精确关键词匹配
     *
     * 粗检索阶段故意放宽阈值（0.5f），让更多候选文档进入 Reranker 精排环节。
     * "宁可多召回，让 Reranker 来精筛"——这是两阶段检索的核心思想。
     */
    private List<DocumentChunk> executeCoarseRetrieval(RewriteResult rewriteResult) {
        Map<String, DocumentChunk> docMap = new LinkedHashMap<>();

        // 1. 语义搜索：对每个 semanticQuery 执行向量检索
        for (String semanticQuery : rewriteResult.semanticQueries()) {
            try {
                List<DocumentChunk> chunks = esVectorStore.search(
                        semanticQuery, COARSE_TOP_K, COARSE_SIMILARITY_THRESHOLD);
                for (DocumentChunk chunk : chunks) {
                    String key = chunk.getArticleId() + "_" + chunk.getChunkIndex();
                    if (!docMap.containsKey(key)) {
                        docMap.put(key, chunk);  // 直接复用 DocumentChunk
                    }
                }
            } catch (Exception e) {
                log.error("语义搜索失败, query: {}", semanticQuery, e);
            }
        }

        // 2. 关键词搜索：ES 全文搜索，与语义搜索互补
        for (String keyword : rewriteResult.keywords()) {
            try {
                PageVO<ArticleSearchVO> pageResult = esComponent.search(
                        false, keyword, null, 1, 5);
                List<ArticleSearchVO> articles = pageResult.getRecords();
                if (articles != null) {
                    for (ArticleSearchVO article : articles) {
                        String key = "keyword_" + article.getArticleId();
                        if (!docMap.containsKey(key)) {
                            // 将 ArticleSearchVO 转为 DocumentChunk
                            DocumentChunk chunk = new DocumentChunk();
                            chunk.setArticleId(article.getArticleId());
                            chunk.setTitle(article.getTitle());
                            chunk.setContent(article.getSummary() != null ? article.getSummary() : "");
                            chunk.setScore(0.5);  // 关键词搜索无向量分数，给默认值
                            docMap.put(key, chunk);
                        }
                    }
                }
            } catch (Exception e) {
                log.error("关键词全文搜索失败, keyword: {}", keyword, e);
            }
        }

        log.info("粗检索完成: 语义queries={}, 关键词={}, 去重后候选文档={}",
                rewriteResult.semanticQueries().size(),
                rewriteResult.keywords().size(),
                docMap.size());

        return new ArrayList<>(docMap.values());
    }

    /**
     * 将精排后的文档构建为 RAG context 文本
     */
    private String buildRagContext(List<DocumentChunk> relevantDocs) {
        if (relevantDocs.isEmpty()) return "";

        StringBuilder context = new StringBuilder();
        for (int i = 0; i < relevantDocs.size(); i++) {
            DocumentChunk doc = relevantDocs.get(i);
            context.append(String.format("【参考%d】(相关性: %.2f) 来自《%s》:\n%s\n\n",
                    i + 1, doc.getScore(), doc.getTitle(), doc.getContent()));
        }
        return context.toString();
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}

@Slf4j
@Component
@RequiredArgsConstructor
public class DispatcherNode implements NodeAction {

    private final ChatModel chatModel;
    private final ArticleTool articleTool;
    
    // 直接注入各个 Worker（都是 @Component）
    private final SearchWorkerNode searchWorkerNode;
    private final AnalysisWorkerNode analysisWorkerNode;
    private final WritingWorkerNode writingWorkerNode;
    private final ChatWorkerNode chatWorkerNode;

    // createWorker 方法：直接返回注入的 Bean
    private NodeAction createWorker(String workerName) {
        return switch (workerName) {
            case "search" -> searchWorkerNode;
            case "analysis" -> analysisWorkerNode;
            case "writing" -> writingWorkerNode;
            case "chat" -> chatWorkerNode;
            default -> throw new IllegalArgumentException("未知的Worker: " + workerName);
        };
    }
    
    // ... 其他方法不变
}
```

### 3.7 AgentGraphConfiguration 改造

由于 `DispatcherNode` 也改为 `@Component`，直接注入即可：

```java
@Bean("compiledAgentGraph")
public CompiledGraph compiledAgentGraph(DispatcherNode dispatcherNode) throws GraphStateException {
    // ...
    .addNode("dispatcher", node_async(dispatcherNode))
    // ...
}
```

### 3.8 AgentStateFactory 无需改动

当前的 state 定义已经足够支持两阶段检索：
- `historyMessages`：SearchWorkerNode 读取（用于 Query Rewrite）
- `workerResults`：AppendStrategy，不变
- `searchResult`：ReplaceStrategy，不变

## 四、性能与成本分析

### 新旧方案对比

| 环节 | 旧方案（LLM Grade） | 新方案（Reranker） |
|------|---------------------|-------------------|
| Query Rewrite | 1次 LLM 调用，~700 tokens | 1次 LLM 调用，~700 tokens（不变） |
| 粗检索 | 向量搜索 5 个 | 向量搜索 + 关键词搜索，20-30 个候选 |
| 相关性评估 | 1次 LLM 调用，~1000 tokens（文档摘要全发给 LLM） | 1次 Reranker API 调用，~$0.0001（0.6B 小模型） |
| 重试（最坏） | 额外 4 次 LLM 调用 | 额外 2 次 LLM（rewrite）+ 2 次 Reranker |
| **总计最佳情况** | **3 次 LLM 调用**（rewrite + grade + 生成） | **2 次 LLM 调用**（rewrite + 生成）+ 1 次 Reranker |
| **总计最坏情况** | **9 次 LLM 调用** | **4 次 LLM 调用** + 3 次 Reranker |

### 4.2 延迟分析

| 环节 | 耗时估算 |
|------|----------|
| Query Rewrite（LLM） | 1-2s |
| 粗检索（ES 向量 + 关键词） | 50-200ms |
| Reranker 精排（20-30 个文档） | 200-500ms |
| LLM 生成回答 | 2-5s |
| **总计** | **3.5-8s**（旧方案 5-12s） |

### 4.3 优化策略

1. **异步并行粗检索**：多个 semanticQuery 的向量检索 + 关键词检索可以用 `CompletableFuture` 并行执行
2. **缓存重写结果**：相同 query 的重写结果可以缓存（Redis，TTL 5分钟）
3. **Reranker 批量调用**：一次 API 调用处理所有候选文档，无需逐个调用
4. **提前终止**：如果粗检索阶段有文档向量相似度 > 0.9，可以跳过 Reranker 直接使用

## 五、实施步骤

### Step 1：新建服务类
1. 创建 `QueryRewriteService.java`（`agent/service/` 下）
2. 创建 `RerankerService.java`（`agent/service/` 下）
3. `application.yml` 新增 Reranker 配置项

### Step 2：改造 SearchWorkerNode
1. 注入 `QueryRewriteService` 和 `RerankerService`（替代旧方案的 `RetrievalGrader`）
2. 将 `apply()` 方法改为两阶段检索流程
3. 粗检索阶段放宽阈值，精排阶段用 Reranker 筛选
4. 保持对外接口不变（输入输出 Map 结构不变）

### Step 3：改造 DispatcherNode
1. 构造函数新增 `EsComponent`、`QueryRewriteService` 和 `RerankerService` 参数
2. `createWorker()` 传递新参数给 `SearchWorkerNode`

### Step 4：验证与调优
1. 测试 Reranker API 连通性和响应格式
2. 对比新旧方案的检索质量（相同 query，观察 Top-5 文档的相关性）
3. 调整 `COARSE_SIMILARITY_THRESHOLD`、`RELEVANCE_THRESHOLD` 等参数
4. 监控 Reranker API 的延迟和成本

## 六、后续扩展方向

| 方向 | 说明 | 优先级 |
|------|------|--------|
| **Reranker 自部署** | 用 BGE-Reranker-v2-m3 自部署，消除对 SiliconFlow 的依赖 | 中 |
| **FlashRank 策略** | 引入 token budget 约束，在 Rerank 时考虑文档间信息冗余，选出信息增益最大的子集（参考 [arxiv 2601.03258](https://arxiv.org/html/2601.03258v1)） | 中 |
| **Adaptive Retrieval** | 根据 query 类型自动选择检索策略（纯向量/纯关键词/混合/联网） | 中 |
| **Query Decomposition** | 复杂问题拆解为多个子问题，分别检索后合并 | 低 |
| **Retrieval Cache** | 缓存高频 query 的检索 + 精排结果，减少重复调用 | 低 |
| **Spring AI RetrievalAugmentationAdvisor** | 等 Spring AI 的 RAG 模块稳定后，考虑迁移到官方 Advisor 体系 | 低（观望） |