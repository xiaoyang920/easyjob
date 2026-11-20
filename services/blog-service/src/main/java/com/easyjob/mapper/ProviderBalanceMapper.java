package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;

import org.apache.ibatis.annotations.Param;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/** Fixed statements with bound parameters; locking reads bypass MyBatis caches. */
@Mapper
public interface ProviderBalanceMapper {
    List<Map<String, Object>> checkSchema();
    int ensureMonitor(@Param("key") String key, @Param("currency") String currency, @Param("fingerprint") String fingerprint, @Param("threshold") BigDecimal threshold, @Param("recipient") String recipient);
    Map<String, Object> lockMonitor(@Param("key") String key);
    int resetMonitor(@Param("fingerprint") String fingerprint, @Param("threshold") BigDecimal threshold, @Param("recipient") String recipient, @Param("accountChanged") boolean accountChanged, @Param("clearChecked") boolean clearChecked, @Param("key") String key);
    int claimLease(@Param("token") String token, @Param("key") String key);
    List<Map<String, Object>> lockLease(@Param("key") String key, @Param("token") String token);
    int recordBalance(@Param("balance") BigDecimal balance, @Param("available") boolean available, @Param("state") String state, @Param("alertId") String alertId, @Param("sentAt") Object sentAt, @Param("key") String key, @Param("token") String token);
    LocalDateTime lastCheckedAt(@Param("key") String key);
    int extendLease(@Param("key") String key, @Param("token") String token, @Param("alertId") String alertId);
    int markSent(@Param("key") String key, @Param("token") String token, @Param("alertId") String alertId);
    int finishLease(@Param("seconds") int seconds, @Param("key") String key, @Param("token") String token);
    int retryLease(@Param("error") String error, @Param("seconds") int seconds, @Param("key") String key, @Param("token") String token);
}
