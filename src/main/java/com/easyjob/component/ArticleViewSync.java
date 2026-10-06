package com.easyjob.component;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.UUID;

/** Durable count-only projection. Rows coalesce reads; leases fence concurrent workers. */
@Component @Slf4j
public class ArticleViewSync {
    private final JdbcTemplate jdbc;
    private final EsComponent es;
    private final TransactionTemplate transactions;
    public record Job(long articleId, int count, int attempts, String token) {}
    public ArticleViewSync(JdbcTemplate jdbc, EsComponent es, PlatformTransactionManager manager) {
        this.jdbc=jdbc; this.es=es; this.transactions=new TransactionTemplate(manager);
    }
    @PostConstruct void checkSchema() {
        jdbc.queryForList("SELECT article_id,target_count,attempts,available_at,lease_token,lease_until,last_error FROM article_view_sync LIMIT 0");
    }
    /** Must be called in the transaction committing the authoritative reading count. */
    public void enqueue(long aid, int count) {
        jdbc.update("""
            INSERT INTO article_view_sync(article_id,target_count,available_at) VALUES (?,?,TIMESTAMPADD(SECOND,2,UTC_TIMESTAMP(6)))
            ON DUPLICATE KEY UPDATE target_count=GREATEST(target_count,VALUES(target_count)),updated_at=UTC_TIMESTAMP(6)
            """,aid,count);
    }
    public Job claim() {
        return transactions.execute(status -> {
            var rows=jdbc.queryForList("""
                SELECT article_id,target_count,attempts FROM article_view_sync WHERE available_at<=UTC_TIMESTAMP(6)
                AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6))
                ORDER BY available_at,article_id LIMIT 1 FOR UPDATE SKIP LOCKED
                """);
            if(rows.isEmpty()) return null;
            var row=rows.getFirst(); String token=UUID.randomUUID().toString();
            long aid=((Number)row.get("article_id")).longValue();
            jdbc.update("UPDATE article_view_sync SET lease_token=?,lease_until=TIMESTAMPADD(SECOND,30,UTC_TIMESTAMP(6)) WHERE article_id=?",token,aid);
            return new Job(aid,((Number)row.get("target_count")).intValue(),((Number)row.get("attempts")).intValue(),token);
        });
    }
    public void complete(Job job) {
        // An arriving larger count must survive acknowledgement of an older value.
        int removed=jdbc.update("DELETE FROM article_view_sync WHERE article_id=? AND lease_token=? AND target_count<=?",job.articleId(),job.token(),job.count());
        if(removed==0) jdbc.update("""
            UPDATE article_view_sync SET attempts=0,last_error=NULL,lease_token=NULL,lease_until=NULL,
                available_at=TIMESTAMPADD(SECOND,1,UTC_TIMESTAMP(6)) WHERE article_id=? AND lease_token=?
            """,job.articleId(),job.token());
    }
    public static int retrySeconds(int attempts) { return Math.min(300, 1 << Math.min(9, Math.max(1, attempts+1))); }
    public void retry(Job job, String error) {
        jdbc.update("""
            UPDATE article_view_sync SET attempts=LEAST(attempts+1,30),last_error=?,lease_token=NULL,lease_until=NULL,
                available_at=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6)) WHERE article_id=? AND lease_token=?
            """,error,retrySeconds(job.attempts()),job.articleId(),job.token());
    }
    public boolean syncOnce() {
        Job job=claim(); if(job==null) return false;
        try {
            var rows=jdbc.queryForList("SELECT status,deleted FROM article_info WHERE article_id=?",job.articleId());
            // Never create a search document for deleted or unpublished content.
            if(rows.isEmpty() || ((Number)rows.getFirst().get("status")).intValue()!=1 || ((Number)rows.getFirst().get("deleted")).intValue()!=0) complete(job);
            else if(es.syncViewCount(Long.toString(job.articleId()),job.count())) complete(job);
            else retry(job,"es_unavailable_or_document_missing");
        } catch(Exception error) {
            retry(job,error.getClass().getSimpleName());
            log.warn("阅读量同步待重试: articleId={} error={}",job.articleId(),error.getClass().getSimpleName());
        }
        return true;
    }
    @Scheduled(fixedDelayString="${article.view-sync.poll-ms:1000}")
    public void poll() {
        try { for(int i=0;i<10 && syncOnce();i++) { /* bounded batch */ } }
        catch(Exception error) { log.warn("阅读量同步队列暂时不可用: {}",error.getClass().getSimpleName()); }
    }
}
