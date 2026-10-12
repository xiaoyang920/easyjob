package com.easyjob.component;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import com.easyjob.mapper.ArticleViewSyncMapper;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.util.UUID;

/** Durable count-only projection. Rows coalesce reads; leases fence concurrent workers. */
@Component @Slf4j
public class ArticleViewSync {
    private final ArticleViewSyncMapper store;
    private final EsComponent es;
    private final TransactionTemplate transactions;
    public record Job(long articleId, int count, int attempts, String token) {}
    public ArticleViewSync(ArticleViewSyncMapper store, EsComponent es, PlatformTransactionManager manager) {
        this.store=store; this.es=es; this.transactions=new TransactionTemplate(manager);
    }
    @PostConstruct void checkSchema() {
        store.checkSchema();
    }
    /** Must be called in the transaction committing the authoritative reading count. */
    public void enqueue(long aid, int count) {
        store.enqueue(aid,count);
    }
    public Job claim() {
        return transactions.execute(status -> {
            var rows=store.lockAvailableJob();
            if(rows.isEmpty()) return null;
            var row=rows.getFirst(); String token=UUID.randomUUID().toString();
            long aid=((Number)row.get("article_id")).longValue();
            store.leaseJob(token,aid);
            return new Job(aid,((Number)row.get("target_count")).intValue(),((Number)row.get("attempts")).intValue(),token);
        });
    }
    public void complete(Job job) {
        // An arriving larger count must survive acknowledgement of an older value.
        int removed=store.completeJob(job.articleId(),job.token(),job.count());
        if(removed==0) store.releaseNewerTarget(job.articleId(),job.token());
    }
    public static int retrySeconds(int attempts) { return Math.min(300, 1 << Math.min(9, Math.max(1, attempts+1))); }
    public void retry(Job job, String error) {
        store.retryJob(error,retrySeconds(job.attempts()),job.articleId(),job.token());
    }
    public boolean syncOnce() {
        Job job=claim(); if(job==null) return false;
        try {
            var rows=store.findArticleVisibility(job.articleId());
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
