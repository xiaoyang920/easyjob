package com.easyjob.agent.component;

import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleVectorMessage;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.util.concurrent.TimeUnit;

@Component
@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(name="agent.index-outbox.enabled",havingValue="true",matchIfMissing=true)
@Slf4j
public class ArticleIndexRelay {
    private final ArticleIndexOutbox outbox;
    private final RabbitTemplate rabbit;

    public ArticleIndexRelay(ArticleIndexOutbox outbox, RabbitTemplate rabbit) {
        this.outbox = outbox;
        this.rabbit = rabbit;
        rabbit.setMandatory(true);
    }

    @Scheduled(fixedDelayString = "${agent.index-outbox.poll-ms:1000}")
    public void poll() {
        try {
            for (int i = 0; i < 10 && relayOnce(); i++) { /* bounded batch */ }
        } catch (Exception error) {
            log.warn("文章索引任务领取失败: {}", error.getClass().getSimpleName());
        }
    }

    public boolean relayOnce() {
        var job = outbox.claim();
        if (job == null) return false;
        try {
            var correlation = new CorrelationData(job.id());
            var message = new ArticleVectorMessage(job.articleId(), job.action());
            message.setIndexJobId(job.id());
            rabbit.convertAndSend(RabbitMqConstants.TOPIC_EXCHANGE, job.routingKey(), message, correlation);
            var confirm = correlation.getFuture().get(5, TimeUnit.SECONDS);
            if (!confirm.isAck() || correlation.getReturned() != null)
                throw new IllegalStateException("Index message was not accepted/routed");
            outbox.dispatched(job);
        } catch (Exception error) {
            if (error instanceof InterruptedException) Thread.currentThread().interrupt();
            outbox.retry(job, error);
            log.warn("文章索引投递失败: articleId={} attempt={} error={}", job.articleId(), job.attempts(), error.getClass().getSimpleName());
        }
        return true;
    }
}
