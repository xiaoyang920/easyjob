package com.easyjob.billing;

import lombok.extern.slf4j.Slf4j;
import com.easyjob.billing.DeepseekBalanceClient.Balance;
import com.easyjob.billing.ProviderBalanceStore.Lease;
import com.easyjob.billing.ProviderBalanceStore.Notice;

@Slf4j
public class DeepseekBalanceMonitor {
    private final ProviderBalanceStore store;
    private final BalanceAlertPolicy policy;
    private final DeepseekBalanceClient provider;
    private final DeepseekBalanceMail mail;
    public DeepseekBalanceMonitor(ProviderBalanceStore store, BalanceAlertPolicy policy,
                                  DeepseekBalanceClient provider, DeepseekBalanceMail mail) {
        this.store=store; this.policy=policy; this.provider=provider; this.mail=mail;
    }
    public void checkSchema() { store.checkSchema(); }
    public boolean tick() {
        Lease lease = store.claim(policy, provider.fingerprint());
        if (lease == null) return false;
        String stage = "balance_check";
        try {
            Balance balance = provider.fetch(policy.currency());
            Notice notice = store.record(lease, policy, balance);
            if (notice != null) {
                store.beforeSend(lease, notice);
                stage = "email_delivery";
                mail.send(notice);
                store.sent(lease, notice);
                log.info("DeepSeek low-balance email accepted by SMTP: alert={}", notice.id());
            }
            store.finish(lease, policy.intervalSeconds());
        } catch (ProviderBalanceStore.LeaseLost error) {
            log.warn("DeepSeek balance monitor lease lost; waiting for the current owner");
        } catch (Exception error) {
            String code = error instanceof DeepseekBalanceClient.CheckFailed ? error.getMessage() : stage + "_failed";
            store.retry(lease, code);
            log.warn("DeepSeek balance monitor will retry: {}", code);
        }
        return true;
    }
}
