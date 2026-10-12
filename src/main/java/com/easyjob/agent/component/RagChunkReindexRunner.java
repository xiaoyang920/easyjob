package com.easyjob.agent.component;

import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.entity.Article;
import com.easyjob.listener.ArticleVectorListener;
import com.easyjob.mapper.ArticleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/** Explicit opt-in, paged rebuild; normal starts never invoke embeddings for old articles. */
@Component
@Order(10)
@RequiredArgsConstructor
@Slf4j
@ConditionalOnProperty(name = "rag.reindex.enabled", havingValue = "true")
public class RagChunkReindexRunner implements ApplicationRunner {
    private final ArticleMapper articles;
    private final ArticleVectorListener indexer;

    @Override public void run(ApplicationArguments args) {
        long after = 0;
        int count = 0;
        while (true) {
            var page = articles.findReindexPage(after);
            if (page.isEmpty()) break;
            for (Article article : page) {
                indexer.handleVectorMessage(new ArticleVectorMessage(article.getArticleId(), "UPDATE"));
                after = article.getArticleId();
                count++;
            }
            log.info("HTML块重建进度：已完成{}篇，最后article_id={}", count, after);
        }
        log.info("HTML块重建完成：{}篇", count);
    }
}
