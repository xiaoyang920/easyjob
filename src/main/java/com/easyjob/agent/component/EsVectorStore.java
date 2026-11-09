package com.easyjob.agent.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.bulk.BulkOperation;
import co.elastic.clients.json.JsonData;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import com.easyjob.agent.service.ArticleEmbeddingService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.io.StringReader;
import java.util.ArrayList;
import java.util.List;

import static com.easyjob.constants.AgentEsConstants.*;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import co.elastic.clients.elasticsearch.core.DeleteByQueryResponse;
import co.elastic.clients.elasticsearch.core.UpdateByQueryResponse;

@Slf4j
@Component
public class EsVectorStore {
    @Autowired
    private  ElasticsearchClient esClient;
    @Autowired
    private ArticleEmbeddingService articleEmbeddingService;
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
            esClient.indices().putMapping(m -> m.index(VECTOR_INDEX).withJson(new StringReader(CHUNK_METADATA_MAPPING)));
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
            List<List<Double>> vectors = articleEmbeddingService.embed(
                    chunks.stream().map(DocumentChunk::getEmbeddingText).toList());
            if (vectors.size() != chunks.size()) throw new BusinessException("Embedding返回数量与文本块不一致");
            for(int i = 0; i < chunks.size(); i++){
                DocumentChunk chunk = chunks.get(i);
                List<Double> vector = vectors.get(i);
                if (vector == null || vector.size() != 2048 || vector.stream().anyMatch(v -> v == null || !Double.isFinite(v))) {
                    throw new BusinessException("Embedding维度或数值不兼容，未提交索引");
                }
                chunk.setVector(vector);
                //构建批量操作
                String chunkId = chunk.getChunkId();
                operations.add(BulkOperation.of(op->op
                        .index(idx->idx
                                .index(VECTOR_INDEX)
                                .id(chunkId)
                                .document(chunk.toEsDocument())
                        )
                ));
            }
            //批量保存向量数据
            BulkResponse response = esClient.bulk(b->b.operations(operations).refresh(co.elastic.clients.elasticsearch._types.Refresh.WaitFor));
            if (response.errors()) throw new BusinessException("文本块批量索引部分失败，需重试");
            log.info("成功存储 {} 个文档块", chunks.size());
        } catch (Exception e) {
            log.error("保存向量数据失败", e);
            throw new BusinessException("保存向量数据失败");
        }
    }

    /** Called under the shared per-article indexing lock, after a complete bulk write. */
    public void retainChunks(String articleId, List<DocumentChunk> chunks) {
        try {
            List<String> ids = chunks.stream().map(DocumentChunk::getChunkId).toList();
            DeleteByQueryResponse response = esClient.deleteByQuery(d -> d.index(VECTOR_INDEX).refresh(true).query(q -> q.bool(b -> b
                    .filter(f -> f.term(t -> t.field("article_id").value(articleId)))
                    .mustNot(n -> n.ids(i -> i.values(ids))))));
            if (Boolean.TRUE.equals(response.timedOut()) || !response.failures().isEmpty()) throw new BusinessException("旧文本块未完全清理");
        } catch (Exception e) {
            throw new BusinessException("旧文本块清理失败，需重试", e);
        }
    }
    /**
     * 更新文章所有向量块的热度计数
     *
     * @param articleId 文章ID
     * @param fieldName 字段名（like_count 或 collect_count）
     * @param delta     增量值（正数增加，负数减少）
     */
    public void syncInteractionCounts(String articleId, int likes, int collects) {
        try {
            UpdateByQueryResponse response = esClient.updateByQuery(u -> u.index(VECTOR_INDEX)
                    .query(q -> q.term(t -> t.field("article_id").value(articleId)))
                    .script(s -> s.source("ctx._source.like_count = params.likes; ctx._source.collect_count = params.collects;")
                            .params("likes", JsonData.of(likes)).params("collects", JsonData.of(collects))));
            if (Boolean.TRUE.equals(response.timedOut()) || !response.failures().isEmpty()
                    || (response.versionConflicts() != null && response.versionConflicts() > 0)) {
                throw new BusinessException("文本块热度未完全同步");
            }
        } catch (Exception exception) {
            throw new BusinessException("文本块热度同步失败，需重试", exception);
        }
    }

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
            DeleteByQueryResponse response = esClient.deleteByQuery(d -> d
                    .index(VECTOR_INDEX)
                    .refresh(true)
                    .query(q -> q
                            .term(m -> m
                                    .field("article_id")
                                    .value(articleId)
                            )
                    )
            );
            if (Boolean.TRUE.equals(response.timedOut()) || !response.failures().isEmpty()) throw new BusinessException("文章文本块未完全删除");
            log.info("删除向量索引成功，articleId: {}", articleId);
        } catch (Exception e) {
            log.error("删除文章向量失败, articleId={}", articleId, e);
            throw new BusinessException("删除文章文本块失败，需重试", e);
        }
    }
}
