package com.easyjob.listener;

import com.easyjob.agent.component.DocumentChunkService;
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

/**
 * 文章向量索引消费者
 *
 * 【职责】
 * 1. 监听文章发布/更新消息，执行分块+向量入库
 * 2. 监听文章删除消息，清理向量数据
 *
 * 【重试策略】
 * 由RabbitMQ listener.retry配置控制：
 * - 最多重试3次
 * - 间隔递增（1s → 2s → 4s）
 * - 最终失败记日志丢弃
 */
@Component
@Slf4j
public class ArticleVectorListener {
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired
    private DocumentChunkService documentChunkService;
    @Autowired
    private EsVectorStore esVectorStore;
    @Autowired
    private ArticleTagMapper articleTagMapper;
    /**
     * 处理文章向量索引消息
     * @param message
     */
    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_INDEX)
    public void handleVectorMessage(ArticleVectorMessage message) {
        Long articleId = message.getArticleId();
        String action = message.getAction();
        log.info("收到向量索引信息:articleId={},action={}", articleId, action);
        Article article = articleMapper.selectById(articleId);
        if(article== null){
            throw new BusinessException("文章不存在");
        }
        // 更新先删除
        if("UPDATE".equals(action)){
            esVectorStore.deleteByArticleId(articleId.toString());
        }
        List<TagVO> tags = articleTagMapper.getTagsByArticleId(articleId);
        List<String> tagList = tags.stream().map(TagVO::getTagName).toList();
        //分块
        List<DocumentChunk> chunks = documentChunkService.chunk(
                articleId.toString(),
                article.getTitle(),
                article.getContent(),
                article.getUserId(),
                tagList
        );
        esVectorStore.saveChunks(chunks);
        log.info("向量索引完成: articleId={}, action={}, chunks={}",
                articleId, action, chunks.size());
    }
    /**
     * 处理文章删除消息
     * @param message
     */
    @RabbitListener(queues = RabbitMqConstants.QUEUE_VECTOR_DELETE)
    public void handleVectorDelete(ArticleVectorMessage message){
        Long articleId = message.getArticleId();
        log.info("收到向量删除信息:articleId={}", articleId);
        esVectorStore.deleteByArticleId(articleId.toString());
        log.info("向量删除完成: articleId={}", articleId);
    }
}
