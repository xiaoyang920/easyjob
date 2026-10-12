package com.easyjob.component;

import com.easyjob.exception.BusinessException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Coalesces cache misses across instances; this is not a database consistency lock. */
@Component
public class CacheRebuildMutex {
    private static final Logger log = LoggerFactory.getLogger(CacheRebuildMutex.class);
    private static final DefaultRedisScript<Long> RELEASE = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
            Long.class);
    private final StringRedisTemplate redis;
    private final Duration lease;
    private final long waitNanos;

    public CacheRebuildMutex(StringRedisTemplate redis,
            @Value("${easyjob.cache.rebuild-lock-lease-ms:30000}") long leaseMillis,
            @Value("${easyjob.cache.rebuild-wait-ms:2000}") long waitMillis) {
        if (leaseMillis <= 0 || waitMillis < 0) throw new IllegalArgumentException("Invalid cache lock timeouts");
        this.redis = redis;
        this.lease = Duration.ofMillis(leaseMillis);
        this.waitNanos = TimeUnit.MILLISECONDS.toNanos(waitMillis);
    }

    public <T> T getOrLoad(String cacheKey, Supplier<T> readCache, Supplier<T> load,
                           Consumer<T> writeCache) {
        T cached = readCache.get();
        if (cached != null) return cached;
        String lockKey = cacheKey + ":rebuild-lock";
        String owner = UUID.randomUUID().toString();
        long started = System.nanoTime();
        while (true) {
            if (Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(lockKey, owner, lease))) {
                try {
                    // A previous owner may have filled the cache before we acquired the lock.
                    cached = readCache.get();
                    if (cached != null) return cached;
                    T loaded = load.get();
                    // Avoid publishing after a known lease expiry. The lease is crash recovery,
                    // not a fence against concurrent database edits.
                    if (loaded != null && owner.equals(redis.opsForValue().get(lockKey))) {
                        writeCache.accept(loaded);
                    }
                    return loaded;
                } finally {
                    try {
                        redis.execute(RELEASE, List.of(lockKey), owner);
                    } catch (RuntimeException exception) {
                        // A release failure must not mask a successful read or the loader error.
                        log.warn("Cache rebuild lock release failed, key={}; lease will expire", lockKey);
                    }
                }
            }
            cached = readCache.get();
            if (cached != null) return cached;
            long remaining = waitNanos - (System.nanoTime() - started);
            if (remaining <= 0) {
                // Do not let every waiter fall through to the database and recreate a stampede.
                throw new BusinessException(503, "文章正在加载，请稍后重试");
            }
            try {
                TimeUnit.NANOSECONDS.sleep(Math.min(remaining, TimeUnit.MILLISECONDS.toNanos(50)));
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new BusinessException(503, "文章加载已中断", exception);
            }
        }
    }
}
