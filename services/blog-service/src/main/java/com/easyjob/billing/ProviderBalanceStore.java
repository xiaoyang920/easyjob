package com.easyjob.billing;

import com.easyjob.mapper.ProviderBalanceMapper;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.*;
import java.util.List;
import java.util.Map;

/** One durable monitor row includes the pending notification, check lease and retry time. */
public class ProviderBalanceStore {
    public record Lease(String key, String token, int failures) {}
    public record Notice(String id, String recipient, String currency, BigDecimal threshold,
                         BigDecimal balance, LocalDateTime checkedAt) {}
    public static class LeaseLost extends RuntimeException {}
    private final ProviderBalanceMapper mapper;
    private final TransactionTemplate transactions;

    public ProviderBalanceStore(ProviderBalanceMapper mapper, PlatformTransactionManager manager) {
        this.mapper = mapper; transactions = new TransactionTemplate(manager);
    }
    public void checkSchema() {
        mapper.checkSchema();
    }
    public Lease claim(BalanceAlertPolicy policy, String fingerprint) {
        return transactions.execute(tx -> {
            mapper.ensureMonitor(policy.key(), policy.currency(), fingerprint, policy.threshold(), policy.recipient());
            Map<String, Object> row = mapper.lockMonitor(policy.key());
            if (!truth(row.get("unlocked"))) return null;
            boolean accountChanged = !fingerprint.equals(row.get("account_fingerprint"));
            boolean changed = accountChanged || !policy.recipient().equals(row.get("recipient"))
                    || policy.threshold().compareTo((BigDecimal)row.get("threshold_amount")) != 0;
            if (!changed && !truth(row.get("due"))) return null;
            String token = UUID.randomUUID().toString();
            if (changed) mapper.resetMonitor(fingerprint, policy.threshold(), policy.recipient(), accountChanged, accountChanged, policy.key());
            mapper.claimLease(token, policy.key());
            return new Lease(policy.key(), token, changed ? 0 : ((Number)row.get("failure_count")).intValue());
        });
    }
    public Notice record(Lease lease, BalanceAlertPolicy policy, DeepseekBalanceClient.Balance balance) {
        return transactions.execute(tx -> {
            List<Map<String, Object>> rows = mapper.lockLease(lease.key(), lease.token());
            if (rows.isEmpty()) throw new LeaseLost();
            Map<String, Object> row = rows.getFirst();
            boolean low = policy.low(balance.total());
            boolean sameEpisode = low && "low".equals(row.get("alert_state")) && row.get("alert_id") != null;
            String id = low ? (sameEpisode ? row.get("alert_id").toString() : UUID.randomUUID().toString()) : null;
            Object sentAt = sameEpisode ? row.get("alert_sent_at") : null;
            mapper.recordBalance(balance.total(), balance.available(), low ? "low" : "normal", id, sentAt, lease.key(), lease.token());
            if (!low || sentAt != null) return null;
            LocalDateTime time = mapper.lastCheckedAt(lease.key());
            return new Notice(id, policy.recipient(), policy.currency(), policy.threshold(), balance.total(), time);
        });
    }
    public void beforeSend(Lease lease, Notice notice) {
        int updated = mapper.extendLease(lease.key(), lease.token(), notice.id());
        if (updated != 1) throw new LeaseLost();
    }
    public void sent(Lease lease, Notice notice) {
        int updated = mapper.markSent(lease.key(), lease.token(), notice.id());
        if (updated != 1) throw new LeaseLost();
    }
    public void finish(Lease lease, int intervalSeconds) {
        mapper.finishLease(intervalSeconds, lease.key(), lease.token());
    }
    public void retry(Lease lease, String code) {
        int delay = Math.min(600, 60 * (1 << Math.min(lease.failures(), 4)));
        mapper.retryLease(code, delay, lease.key(), lease.token());
    }
    private static boolean truth(Object value) { return Boolean.TRUE.equals(value) || value instanceof Number number && number.intValue() != 0; }
}
