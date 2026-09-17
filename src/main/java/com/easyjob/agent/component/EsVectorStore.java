package com.easyjob.agent.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.bulk.BulkOperation;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import com.easyjob.agent.service.ZhipuEmbeddingService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.io.StringReader;
import java.util.ArrayList;
import java.util.List;

import static com.easyjob.constants.AgentEsConstants.*;

@Slf4j
@Component
public class EsVectorStore {
    @Autowired
    private  ElasticsearchClient esClient;
    @Autowired
    private ZhipuEmbeddingService embeddingService;
    /**
     * 初始化索引
     */
    public void initIndex(){
        try {
            boolean exists = esClient.indices()
                    .exists(e->e.index(VECTOR_INDEX))
                    .value();
            if(!exists){
                esClient.indices().create(c->c.index(VECTOR_INDEX)
                        .settings(s -> s.withJson(new StringReader(VECTOR_INDEX_SETTINGS)))
                        .mappings(m->m.withJson(new StringReader(VECTOR_INDEX_MAPPING)))
                );
                log.info("创建向量索引{}成功", VECTOR_INDEX);
            }else {
                log.info("向量索引{}已存在", VECTOR_INDEX);
            }
        } catch (Exception e) {
            log.error("向量创建索引失败", e);
            throw new BusinessException("向量创建索引失败");
        }
    }
    /**
     * 保存文档块
     * @param chunks 文档块
     */
    public void saveChunks(List<DocumentChunk> chunks){
        if(chunks== null|| chunks.isEmpty()){
            return;
        }
        try {
            List<BulkOperation> operations = new ArrayList<>();
            for(DocumentChunk chunk: chunks){
                //生成向量
                List<Double> vector = embeddingService.embed(chunk.getContent());
                chunk.setVector(vector);
                //构建批量操作
                String chunkId = chunk.getArticleId() + "_" + chunk.getChunkIndex();
                operations.add(BulkOperation.of(op->op
                        .index(idx->idx
                                .index(VECTOR_INDEX)
                                .id(chunkId)
                                .document(chunk.toEsDocument())
                        )
                ));
            }
            //批量保存向量数据
            esClient.bulk(b->b.operations(operations));
            log.info("成功存储 {} 个文档块", chunks.size());
        } catch (Exception e) {
            log.error("保存向量数据失败", e);
            throw new BusinessException("保存向量数据失败");
        }
    }
    /**
     * 向量搜索（KNN + 热度混合评分）
     *
     * 评分策略：先用KNN召回候选集，再根据热度对结果排序
     * 热度计算：like_count * 2 + collect_count
     *
     * @param query     查询文本
     * @param topK      返回数量
     * @param threshold 相似度阈值
     * @return 搜索结果
     */
    public List<DocumentChunk> search(String query, int topK, float threshold) {
        try {
            // 将文本转换为向量
            List<Double> queryVector = embeddingService.embed(query);

            // List<Double> 转 List<Float>，ES KNN 查询需要 List<Float>
            List<Float> floatVector = queryVector.stream()
                    .map(Double::floatValue)
                    .toList();

            // KNN预检索：取更多候选用于后续热度排序
            int candidates = Math.max(topK * 3, 20);

            // 先用KNN召回候选集
            SearchResponse<DocumentChunk> response = esClient.search(s -> s
                            .index(VECTOR_INDEX)
                            .knn(k -> k
                                    .field("content_vector")
                                    .queryVector(floatVector)
                                    .k(candidates)
                                    .numCandidates(candidates * 2)
                            )
                            .size(candidates),
                    DocumentChunk.class
            );

            // 过滤低分结果并计算混合得分
            List<DocumentChunk> results = new ArrayList<>();
            response.hits().hits().forEach(hit -> {
                if (hit.score() != null && hit.score() >= threshold) {
                    DocumentChunk chunk = hit.source();
                    if (chunk != null) {
                        // 混合评分：KNN相似度 * 0.7 + 热度归一化 * 0.3
                        double knnScore = hit.score();
                        int likeCount = chunk.getLikeCount() != null ? chunk.getLikeCount() : 0;
                        int collectCount = chunk.getCollectCount() != null ? chunk.getCollectCount() : 0;
                        double popularityScore = Math.min(Math.log1p(likeCount * 2 + collectCount) / 10.0, 1.0);
                        double finalScore = knnScore * 0.7 + popularityScore * 0.3;
                        
                        chunk.setScore(finalScore);
                        results.add(chunk);
                    }
                }
            });

            // 按混合得分降序排序，取topK
            results.sort((a, b) -> Double.compare(b.getScore(), a.getScore()));
            List<DocumentChunk> topResults = results.size() > topK ? results.subList(0, topK) : results;

            log.info("向量搜索完成（混合评分），查询: {}, 返回: {} 条", query, topResults.size());
            return topResults;
        } catch (Exception e) {
            log.error("向量搜索失败", e);
            return List.of();
        }
    }

    /**
     * 更新文章所有向量块的热度计数
     *
     * @param articleId 文章ID
     * @param fieldName 字段名（like_count 或 collect_count）
     * @param delta     增量值（正数增加，负数减少）
     */
    public void updateChunkCounts(String articleId, String fieldName, int delta) {
        try {
            // 使用原生JSON方式构建updateByQuery请求，避免API兼容性问题
            String requestJson = String.format(
                "{\"query\":{\"term\":{\"article_id\":\"%s\"}},\"script\":{\"source\":\"ctx._source.%s = Math.max(0, (ctx._source.%s ?: 0) + %d)\"}}",
                articleId, fieldName, fieldName, delta
            );
            
            esClient.updateByQuery(u -> u
                    .index(VECTOR_INDEX)
                    .withJson(new StringReader(requestJson))
            );
            log.info("更新向量索引热度成功, articleId={}, field={}, delta={}", articleId, fieldName, delta);
        } catch (Exception e) {
            log.error("更新向量索引热度失败, articleId={}, field={}, delta={}", articleId, fieldName, delta, e);
        }
    }
    /**
     * 删除整个文章的向量索引
     * @param articleId 文章ID
     */
    public void deleteByArticleId(String articleId){
        try {
            esClient.deleteByQuery(d -> d
                    .index(VECTOR_INDEX)
                    .query(q -> q
                            .term(m -> m
                                    .field("article_id")
                                    .value(articleId)
                            )
                    )
            );
            log.info("删除向量索引成功，articleId: {}", articleId);
        } catch (Exception e) {
            log.error("删除文章向量失败, articleId={}", articleId, e);
        }
    }
}
