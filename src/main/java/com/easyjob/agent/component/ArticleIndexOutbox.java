package com.easyjob.agent.component;

import jakarta.annotation.PostConstruct;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.UUID;

/** Durable delivery intent. Broker acknowledgement is not indexing completion. */
@Component
public class ArticleIndexOutbox {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private static final int MAX_ATTEMPTS = 8;
    public record Job(String id, Long articleId, String action, String routingKey, int attempts, String token) {}

    public ArticleIndexOutbox(JdbcTemplate jdbc, PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        this.transactions = new TransactionTemplate(manager);
    }

    @PostConstruct
    void checkSchema() {
        jdbc.queryForList("SELECT job_id,article_id,action,routing_key,status,attempts,available_at,lease_until,lease_token,last_error FROM article_index_outbox LIMIT 0");
    }

    public void enqueue(Long articleId, String action, String routingKey) {
        if (articleId == null || articleId <= 0) throw new IllegalArgumentException("Invalid article id");
        jdbc.update("INSERT INTO article_index_outbox(job_id,article_id,action,routing_key,available_at,created_at,updated_at) VALUES (?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
                UUID.randomUUID().toString(), articleId, action, routingKey);
    }

    public Job claim() {
        var candidates = jdbc.queryForList("""
            SELECT job_id FROM article_index_outbox WHERE
            (status IN ('pending','dispatched') AND available_at<=UTC_TIMESTAMP(6))
            OR (status='running' AND lease_until<=UTC_TIMESTAMP(6))
            ORDER BY available_at,created_at LIMIT 16
            """);
        for (var candidate : candidates) {
            Job claimed = transactions.execute(status -> {
                var rows = jdbc.queryForList("""
                    SELECT job_id,article_id,action,routing_key,attempts FROM article_index_outbox
                    WHERE job_id=? AND ((status IN ('pending','dispatched') AND available_at<=UTC_TIMESTAMP(6))
                    OR (status='running' AND lease_until<=UTC_TIMESTAMP(6))) FOR UPDATE SKIP LOCKED
                    """, candidate.get("job_id"));
                if (rows.isEmpty()) return null;
                var row = rows.getFirst();
                String id = (String) row.get("job_id"), token = UUID.randomUUID().toString();
                int attempts = ((Number) row.get("attempts")).intValue();
                if (attempts >= MAX_ATTEMPTS) {
                    jdbc.update("UPDATE article_index_outbox SET status='dead',lease_until=NULL,last_error='attempts_exhausted' WHERE job_id=?", id);
                    return null;
                }
                jdbc.update("""
                    UPDATE article_index_outbox SET status='running',attempts=attempts+1,lease_token=?,
                    lease_until=TIMESTAMPADD(SECOND,30,UTC_TIMESTAMP(6)) WHERE job_id=?
                    """, token, id);
                return new Job(id, ((Number) row.get("article_id")).longValue(), (String) row.get("action"),
                        (String) row.get("routing_key"), attempts + 1, token);
            });
            if (claimed != null) return claimed;
        }
        return null;
    }

    public void dispatched(Job job) {
        jdbc.update("""
            UPDATE article_index_outbox SET status='dispatched',lease_until=NULL,last_error=NULL,
            available_at=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6))
            WHERE job_id=? AND status='running' AND lease_token=?
            """, Math.max(60, delay(job.attempts())), job.id(), job.token());
    }

    public void retry(Job job, Exception error) {
        jdbc.update("""
            UPDATE article_index_outbox SET status=?,lease_until=NULL,last_error=?,
            available_at=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6))
            WHERE job_id=? AND status='running' AND lease_token=?
            """, job.attempts() >= MAX_ATTEMPTS ? "dead" : "pending", error.getClass().getSimpleName(),
                delay(job.attempts()), job.id(), job.token());
    }

    private int delay(int attempts) { return Math.min(300, 5 * (1 << Math.min(attempts - 1, 10))); }

    public boolean completed(String id, Long articleId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)>0 FROM article_index_outbox WHERE job_id=? AND article_id=? AND status='completed'", Boolean.class, id, articleId));
    }

    public void complete(String id, Long articleId) {
        jdbc.update("UPDATE article_index_outbox SET status='completed',lease_until=NULL,last_error=NULL WHERE job_id=? AND article_id=?", id, articleId);
    }
}
