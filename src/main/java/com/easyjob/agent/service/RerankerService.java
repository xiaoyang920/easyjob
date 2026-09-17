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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

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
