package com.easyjob.listener;

import com.easyjob.agent.component.DocumentChunkService;
import com.easyjob.agent.component.ArticleIndexOutbox;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.entity.Article;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.vo.TagVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Objects;
import java.time.LocalDateTime;
import com.easyjob.component.ArticleIndexLock;

/**
 * 文章向量索引消费者
 *
 * 【职责】
 * 1. 监听文章发布/更新消息，执行分块+向量入库
 * 2. 监听文章删除消息，清理向量数据
 * 3. 处理热度任务，从 MySQL 读取绝对计数后覆盖索引，不重新分块或生成向量
 *
 * 【重试策略】
 * 由RabbitMQ listener.retry配置控制：
 * - 最多重试3次
 * - 间隔递增（1s → 2s → 4s）
 * - 当前消息最终失败不确认Outbox，后台会按限次退避重新投递
 */
@Component
@Slf4j
public class ArticleVectorListener {
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private com.easyjob.component.EsComponent esComponent;
    @Autowired
    private DocumentChunkService documentChunkService;
    @Autowired
    private EsVectorStore esVectorStore;
    @Autowired
    private ArticleTagMapper articleTagMapper;
    @Autowired
    private ArticleIndexLock articleIndexLock;
    @Autowired
    private ArticleIndexOutbox indexOutbox;
    /**
     * 处理文章向量索引消息
     * @param message
     */
    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_INDEX,
            concurrency = "${agent.index-outbox.consumer-concurrency:4}")
    public void handleVectorMessage(ArticleVectorMessage message) {
        consume(message);
    }

    private void indexCurrentArticle(Long articleId) {
        Article article = articleMapper.selectById(articleId);
        if(article == null || !Objects.equals(article.getStatus(), 1) || !Objects.equals(article.getDeleted(), 0)) {
            esVectorStore.deleteByArticleId(articleId.toString());
            esComponent.deleteDoc(articleId);
            return;
        }
        List<TagVO> tags = articleTagMapper.getTagsByArticleId(articleId);
        // AI has no reading-level authorization yet; only level-zero content enters its chunk index.
        if (article.getRequiredLevel()!=null && article.getRequiredLevel()>0) {
            esVectorStore.deleteByArticleId(articleId.toString());
            esComponent.saveDoc(article);
            return;
        }
        List<String> tagList = tags.stream().map(TagVO::getTagName).toList();
        //分块
        List<DocumentChunk> chunks = documentChunkService.chunk(
                articleId.toString(),
                article.getTitle(),
                article.getContent(),
                article.getUserId(),
                tagList
        );
        chunks.forEach(chunk -> {
            chunk.setCategoryId(article.getCategoryId());
            chunk.setPublishTime(article.getPublishTime());
            chunk.setCreateTime(LocalDateTime.now());
            chunk.setLikeCount(article.getLikeCount());
            chunk.setCollectCount(article.getCollectCount());
        });
        if (!chunks.isEmpty()) esVectorStore.saveChunks(chunks);
        Article latest = articleMapper.selectById(articleId);
        if (latest == null || !Objects.equals(latest.getStatus(), 1) || !Objects.equals(latest.getDeleted(), 0)
                || !Objects.equals(article.getContent(), latest.getContent()) || !Objects.equals(article.getTitle(), latest.getTitle())
                || !Objects.equals(article.getUserId(), latest.getUserId()) || !Objects.equals(article.getPublishTime(), latest.getPublishTime())
                || !Objects.equals(article.getCategoryId(), latest.getCategoryId()) || !Objects.equals(article.getTags(), latest.getTags())
                || !Objects.equals(article.getRequiredLevel(), latest.getRequiredLevel())) {
            throw new BusinessException("索引期间文章已变化，需重新读取并重试");
        }
        if (!tagList.equals(articleTagMapper.getTagsByArticleId(articleId).stream().map(TagVO::getTagName).toList())) {
            throw new BusinessException("索引期间标签已变化，需重试");
        }
        if (chunks.isEmpty()) {
            esVectorStore.deleteByArticleId(articleId.toString());
        } else {
            esVectorStore.retainChunks(articleId.toString(), chunks);
        }
        esComponent.saveDoc(latest);
        log.info("文本块索引完成: articleId={}, chunks={}", articleId, chunks.size());
    }
    /**
     * 处理文章删除消息
     * @param message
     */
    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_DELETE)
    public void handleVectorDelete(ArticleVectorMessage message){
        Long articleId = message.getArticleId();
        log.info("收到向量删除信息:articleId={}", articleId);
        // Delayed delete messages cannot erase an article that has since been republished.
        consume(message);
        log.info("向量删除完成: articleId={}", articleId);
    }

    private void consume(ArticleVectorMessage message) {
        withArticleLock(message.getArticleId(), () -> {
            String jobId = message.getIndexJobId();
            if (jobId != null && indexOutbox.completed(jobId, message.getArticleId())) return;
            if (RabbitMqConstants.ACTION_COUNTS.equals(message.getAction())) {
                syncCurrentCounts(message.getArticleId());
            } else {
                indexCurrentArticle(message.getArticleId());
            }
            if (jobId != null) indexOutbox.complete(jobId, message.getArticleId());
        });
    }

    private void syncCurrentCounts(Long articleId) {
        Article article = articleMapper.selectInteractionCounts(articleId);
        // Publication/deletion tasks own document creation/removal. A late count task cannot resurrect one.
        if (article == null || !Objects.equals(article.getStatus(), 1) || !Objects.equals(article.getDeleted(), 0)) return;
        int likes = article.getLikeCount() == null ? 0 : Math.max(0, article.getLikeCount());
        int collects = article.getCollectCount() == null ? 0 : Math.max(0, article.getCollectCount());
        esComponent.syncInteractionCounts(articleId.toString(), likes, collects);
        esVectorStore.syncInteractionCounts(articleId.toString(), likes, collects);
    }

    private void withArticleLock(Long articleId, Runnable work) {
        articleIndexLock.withLock(articleId, work);
    }
}
