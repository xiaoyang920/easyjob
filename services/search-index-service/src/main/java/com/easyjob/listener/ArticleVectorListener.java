package com.easyjob.listener;

import com.easyjob.agent.component.DocumentChunkService;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.ArticleIndexLock;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleEsDTO;
import com.easyjob.dto.ArticleIndexSnapshot;
import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.index.ArticleTextIndex;
import com.easyjob.index.BlogIndexClient;
import com.easyjob.index.IndexingException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.context.annotation.DependsOn;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

@Component
@DependsOn("initializeVectorIndex")
@RequiredArgsConstructor
@Slf4j
public class ArticleVectorListener {
    private final BlogIndexClient blog;
    private final ArticleTextIndex textIndex;
    private final DocumentChunkService chunker;
    private final EsVectorStore vectors;
    private final ArticleIndexLock lock;

    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_INDEX,
            concurrency = "${agent.index-outbox.consumer-concurrency:4}")
    public void handleVectorMessage(ArticleVectorMessage message) {
        consume(message);
    }

    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_DELETE)
    public void handleVectorDelete(ArticleVectorMessage message) {
        // A delayed deletion may arrive after the same article has been republished.
        consume(message);
    }

    private void consume(ArticleVectorMessage message) {
        Long articleId = message.getArticleId();
        lock.withLock(articleId, () -> {
            String jobId = message.getIndexJobId();
            if (jobId != null && blog.completed(jobId, articleId)) return;
            if (RabbitMqConstants.ACTION_COUNTS.equals(message.getAction())) {
                syncCurrentCounts(articleId);
            } else {
                indexCurrentArticle(articleId);
            }
            if (jobId != null) blog.complete(jobId, articleId);
        });
    }

    private void indexCurrentArticle(Long articleId) {
        String id = articleId.toString();
        ArticleIndexSnapshot snapshot = blog.snapshot(articleId);
        ArticleEsDTO article = snapshot.document();
        if (article == null) {
            vectors.deleteByArticleId(id);
            textIndex.deleteDoc(articleId);
            return;
        }
        List<DocumentChunk> chunks = snapshot.requiredLevel() > 0
                ? List.of()
                : chunker.chunk(id, article.getTitle(), article.getContent(), article.getUserId(), snapshot.tags());
        LocalDateTime created = LocalDateTime.now();
        chunks.forEach(chunk -> {
            chunk.setCategoryId(article.getCategoryId());
            chunk.setPublishTime(article.getPublishTime());
            chunk.setCreateTime(created);
            chunk.setLikeCount(article.getLikeCount());
            chunk.setCollectCount(article.getCollectCount());
        });
        if (!chunks.isEmpty()) vectors.saveChunks(chunks);
        ArticleIndexSnapshot latest = blog.snapshot(articleId);
        if (!snapshot.sameContentAs(latest)) {
            throw new IndexingException("索引期间文章已变化，需重新读取并重试");
        }
        if (chunks.isEmpty()) {
            vectors.deleteByArticleId(id);
        } else {
            vectors.retainChunks(id, chunks);
        }
        textIndex.saveDoc(latest.document());
        log.info("文章索引完成: articleId={}, chunks={}", articleId, chunks.size());
    }

    private void syncCurrentCounts(long articleId) {
        ArticleIndexSnapshot.Counts counts = blog.counts(articleId);
        if (!counts.published()) return;
        String id = Long.toString(articleId);
        textIndex.syncInteractionCounts(id, counts.likes(), counts.collects());
        vectors.syncInteractionCounts(id, counts.likes(), counts.collects());
    }
}
