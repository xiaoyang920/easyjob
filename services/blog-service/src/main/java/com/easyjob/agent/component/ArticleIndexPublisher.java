package com.easyjob.agent.component;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Index intent commits atomically with the article and its tag relations. */
@Component
@RequiredArgsConstructor
public class ArticleIndexPublisher {
    private final ArticleIndexOutbox outbox;

    @Transactional
    public void publish(Long articleId, String action, String routingKey) {
        outbox.enqueue(articleId, action, routingKey);
    }
}
