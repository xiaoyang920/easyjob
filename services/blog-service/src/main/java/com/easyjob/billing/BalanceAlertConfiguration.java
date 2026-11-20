package com.easyjob.billing;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import com.easyjob.mapper.ProviderBalanceMapper;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.transaction.PlatformTransactionManager;
import java.math.BigDecimal;

@Configuration
@ConditionalOnProperty(name="deepseek.balance-alert.enabled",havingValue="true")
public class BalanceAlertConfiguration {
    @Bean BalanceAlertPolicy balanceAlertPolicy(
            @Value("${deepseek.balance-alert.monitor-id:deepseek-default}") String id,
            @Value("${deepseek.balance-alert.currency:CNY}") String currency,
            @Value("${deepseek.balance-alert.threshold:2.00}") BigDecimal threshold,
            @Value("${deepseek.balance-alert.recipient:}") String recipient,
            @Value("${deepseek.balance-alert.interval-seconds:600}") int interval) {
        return new BalanceAlertPolicy(id,currency,threshold,recipient,interval);
    }
    @Bean ProviderBalanceStore providerBalanceStore(ProviderBalanceMapper mapper, PlatformTransactionManager transactions) {
        ProviderBalanceStore store = new ProviderBalanceStore(mapper,transactions); store.checkSchema(); return store;
    }
    @Bean DeepseekBalanceClient deepseekBalanceClient(@Value("${spring.ai.deepseek.api-key}") String key, ObjectMapper json) {
        return new DeepseekBalanceClient(key,json);
    }
    @Bean DeepseekBalanceMail deepseekBalanceMail(JavaMailSender sender,@Value("${spring.mail.username}") String from) {
        return new DeepseekBalanceMail(DeepseekBalanceMail.boundedSender(sender),from);
    }
    @Bean DeepseekBalanceMonitor deepseekBalanceMonitor(ProviderBalanceStore store,BalanceAlertPolicy policy,
                                                       DeepseekBalanceClient provider,DeepseekBalanceMail mail) {
        return new DeepseekBalanceMonitor(store,policy,provider,mail);
    }
    @Bean BalanceAlertRunner balanceAlertRunner(DeepseekBalanceMonitor monitor) { return new BalanceAlertRunner(monitor); }
}
