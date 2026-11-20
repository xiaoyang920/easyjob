package com.easyjob.index;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.ElasticsearchException;
import co.elastic.clients.json.JsonData;
import com.easyjob.dto.ArticleEsDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Slf4j
@Component
@RequiredArgsConstructor
public class ArticleTextIndex {
    private static final String INDEX_NAME = "article";
    private final ElasticsearchClient client;

    /**
     * 保存或更新文档到ES
     * @param articleEsDTO 文章索引文档
     */
    public void saveDoc(ArticleEsDTO articleEsDTO){
        try {

            String docId = articleEsDTO.getArticleId().toString();
            boolean exists = client.exists(e -> e.index(INDEX_NAME).id(docId)).value();
            // 判断文档是否存在
            if(exists){
                client.update(u->u
                        .index(INDEX_NAME)
                        .id(docId)
                        .script(s -> s.source("def previous = ctx._source.viewCount; ctx._source.putAll(params.document); if (previous != null && (ctx._source.viewCount == null || ctx._source.viewCount < previous)) { ctx._source.viewCount = previous; }")
                            .params("document", JsonData.of(articleEsDTO))),
                        ArticleEsDTO.class
                );
            }else {
                // Rebuilt documents keep the authoritative counters from MySQL.
                client.index(i -> i
                        .index(INDEX_NAME)
                        .id(docId)
                        .document(articleEsDTO)
                );
                log.info("文档添加成功，articleId={}", docId);
            }
        } catch (IOException e) {
            log.error("保存到es失败，articleId={}", articleEsDTO.getArticleId(), e);
            throw new IndexingException("保存到es失败");
        }
    }

    /**
     * 删除文档
     * @param articleId 文章ID
     */
    public void deleteDoc(Long articleId){
        try {
            client.delete(d->d
                    .index(INDEX_NAME)
                    .id(articleId.toString())
            );
            log.info("文档删除成功，articleId={}", articleId);
        } catch (ElasticsearchException e) {
            if (e.status() == 404) return;
            throw e;
        } catch (IOException e) {
            log.error("删除文档失败，articleId={}", articleId, e);
            throw new IndexingException("删除文档失败");
        }
    }

    /** Assign authoritative interaction counters. Failures must reach the durable outbox retry. */
    public void syncInteractionCounts(String articleId, int likes, int collects) {
        try {
            client.update(u -> u.index(INDEX_NAME).id(articleId).script(s -> s
                    .source("ctx._source.likeCount = params.likes; ctx._source.collectCount = params.collects;")
                    .params("likes", JsonData.of(likes)).params("collects", JsonData.of(collects))), ArticleEsDTO.class);
        } catch (IOException exception) {
            throw new IndexingException("文章热度同步失败，需重试", exception);
        }
    }

}
