package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.service.QueryRewriteService;
import com.easyjob.agent.service.RerankerService;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.DeepSeekSearchTool;
import com.easyjob.component.EsComponent;
import com.easyjob.dto.RewriteResult;
import com.easyjob.entity.AiMessage;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.util.*;

@Slf4j
@Component
public class SearchWorkerNode implements NodeAction {
    @Autowired
    @Qualifier("deepSeekChatModel")
    private  ChatModel chatModel;
    @Autowired
    private  ArticleTool articleTool;
    @Autowired
    private  DeepSeekSearchTool deepSeekSearchTool;
    @Autowired
    private  EsVectorStore esVectorStore;
    @Autowired
    private  EsComponent esComponent;
    @Autowired
    private  QueryRewriteService queryRewriteService;
    @Autowired
    private  RerankerService rerankerService;
    /** 最大重试次数（含首次检索） */
    private static final int MAX_RETRIEVAL_ROUNDS = 3;
    /** 粗检索阶段：每个 semanticQuery 的 topK（放宽，多召回） */
    private static final int COARSE_TOP_K = 5;
    /** 粗检索阶段：相似度阈值（比旧方案的 0.7f 更宽松，让 Reranker 来精筛） */
    private static final float COARSE_SIMILARITY_THRESHOLD = 0.5f;  // 暂时关闭阈值过滤，让 Reranker 来精筛
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
    public Map<String, Object> apply(OverAllState state) throws Exception {
        Long conversationId = state.value("conversationId", 0L);
        String today = java.time.LocalDate.now().toString();

        // 从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
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
                .tools(articleTool, deepSeekSearchTool)
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
        for (String semanticQuery : rewriteResult.getSemanticQueries()) {
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
        for (String keyword : rewriteResult.getKeywords()) {
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
                rewriteResult.getSemanticQueries().size(),
                rewriteResult.getKeywords().size(),
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