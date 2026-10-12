package com.easyjob.agent.component;

import jakarta.annotation.PostConstruct;
import com.easyjob.mapper.ArticleIndexOutboxMapper;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.UUID;

/** Durable delivery intent. Broker acknowledgement is not indexing completion. */
@Component
public class ArticleIndexOutbox {
    private final ArticleIndexOutboxMapper store;
    private final TransactionTemplate transactions;
    private static final int MAX_ATTEMPTS = 8;
    public record Job(String id, Long articleId, String action, String routingKey, int attempts, String token) {}

    public ArticleIndexOutbox(ArticleIndexOutboxMapper store, PlatformTransactionManager manager) {
        this.store = store;
        this.transactions = new TransactionTemplate(manager);
    }

    @PostConstruct
    void checkSchema() {
        store.checkSchema();
    }

    public void enqueue(Long articleId, String action, String routingKey) {
        if (articleId == null || articleId <= 0) throw new IllegalArgumentException("Invalid article id");
        store.enqueue(UUID.randomUUID().toString(),articleId,action,routingKey);
    }

    public Job claim() {
        var candidates = store.findCandidates();
        for (var candidate : candidates) {
            Job claimed = transactions.execute(status -> {
                var rows = store.lockAvailableJob(candidate.get("job_id").toString());
                if (rows.isEmpty()) return null;
                var row = rows.getFirst();
                String id = (String) row.get("job_id"), token = UUID.randomUUID().toString();
                int attempts = ((Number) row.get("attempts")).intValue();
                if (attempts >= MAX_ATTEMPTS) {
                    store.exhaustJob(id);
                    return null;
                }
                store.leaseJob(token,id);
                return new Job(id, ((Number) row.get("article_id")).longValue(), (String) row.get("action"),
                        (String) row.get("routing_key"), attempts + 1, token);
            });
            if (claimed != null) return claimed;
        }
        return null;
    }

    public void dispatched(Job job) {
        store.markDispatched(Math.max(60, delay(job.attempts())),job.id(),job.token());
    }

    public void retry(Job job, Exception error) {
        store.retryJob(job.attempts() >= MAX_ATTEMPTS ? "dead" : "pending",error.getClass().getSimpleName(),delay(job.attempts()),job.id(),job.token());
    }

    private int delay(int attempts) { return Math.min(300, 5 * (1 << Math.min(attempts - 1, 10))); }

    public boolean completed(String id, Long articleId) {
        return Boolean.TRUE.equals(store.isCompleted(id,articleId));
    }

    public void complete(String id, Long articleId) {
        store.markCompleted(id,articleId);
    }
}
