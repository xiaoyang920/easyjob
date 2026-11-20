package com.easyjob.agent.component;

import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.mapper.ArticleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import java.util.List;

/** Explicit opt-in, paged rebuild; normal starts never invoke embeddings for old articles. */
@Component
@Order(10)
@RequiredArgsConstructor
@Slf4j
@ConditionalOnProperty(name = "rag.reindex.enabled", havingValue = "true")
public class RagChunkReindexRunner implements ApplicationRunner {
    private final ArticleMapper articles;
    private final ArticleIndexPublisher publisher;

    @Override public void run(ApplicationArguments args) {
        long after = 0;
        int count = 0;
        while (true) {
            List<Long> page = articles.findReindexPage(after);
            if (page.isEmpty()) break;
            for (Long articleId : page) {
                publisher.publish(articleId, "UPDATE", RabbitMqConstants.ROUTING_KEY_UPDATE);
                after = articleId;
                count++;
            }
            log.info("HTML块重建已排队{}篇，最后article_id={}", count, after);
        }
        log.info("HTML块重建排队完成：{}篇", count);
    }
}
