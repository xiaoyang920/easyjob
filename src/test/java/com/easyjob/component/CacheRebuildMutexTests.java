package com.easyjob.component;

import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings("unchecked")
class CacheRebuildMutexTests {
    StringRedisTemplate redis;
    ValueOperations<String, String> values;
    Map<String, String> locks;
    CacheRebuildMutex mutex;

    @BeforeEach void setup() {
        redis = mock(StringRedisTemplate.class);
        values = mock(ValueOperations.class);
        locks = new ConcurrentHashMap<>();
        when(redis.opsForValue()).thenReturn(values);
        when(values.setIfAbsent(anyString(), anyString(), any(Duration.class)))
                .thenAnswer(call -> locks.putIfAbsent(call.getArgument(0), call.getArgument(1)) == null);
        when(values.get(anyString())).thenAnswer(call -> locks.get(call.getArgument(0)));
        when(redis.execute(any(DefaultRedisScript.class), anyList(), anyString())).thenAnswer(call -> {
            List<String> keys = call.getArgument(1);
            return locks.remove(keys.getFirst(), call.getArgument(2)) ? 1L : 0L;
        });
        mutex = new CacheRebuildMutex(redis, 30000, 2000);
    }

    @Test void hitSkipsLockAndLoader() {
        Supplier<String> loader = mock(Supplier.class);
        assertEquals("cached", mutex.getOrLoad("article:1", () -> "cached", loader, value -> fail()));
        verifyNoInteractions(redis, loader);
    }

    @Test void concurrentMissesAcrossTwoInstancesOnlyLoadOnce() throws Exception {
        var anotherInstance = new CacheRebuildMutex(redis, 30000, 2000);
        var cached = new AtomicReference<String>();
        var loads = new AtomicInteger();
        var writes = new AtomicInteger();
        var readers = ConcurrentHashMap.<Thread>newKeySet();
        var allReading = new CountDownLatch(24);
        var entered = new CountDownLatch(1);
        var finishLoad = new CountDownLatch(1);
        var start = new CountDownLatch(1);
        Supplier<String> read = () -> {
            if (readers.add(Thread.currentThread())) allReading.countDown();
            return cached.get();
        };
        Supplier<String> load = () -> {
            loads.incrementAndGet();
            entered.countDown();
            try {
                if (!finishLoad.await(5, TimeUnit.SECONDS)) throw new AssertionError("Loader not released");
            } catch (InterruptedException exception) {
                throw new AssertionError(exception);
            }
            return "body";
        };
        try (var pool = Executors.newFixedThreadPool(24)) {
            List<Future<String>> results = new java.util.ArrayList<>();
            for (int index = 0; index < 24; index++) {
                var instance = index % 2 == 0 ? mutex : anotherInstance;
                results.add(pool.submit(() -> {
                    start.await();
                    return instance.getOrLoad("article:1", read, load, value -> {
                        writes.incrementAndGet(); cached.set(value);
                    });
                }));
            }
            try {
                start.countDown();
                assertTrue(entered.await(5, TimeUnit.SECONDS));
                assertTrue(allReading.await(5, TimeUnit.SECONDS));
                // A different article can rebuild while the first article is still loading.
                assertEquals("other", mutex.getOrLoad("article:2", () -> null, () -> "other", value -> {}));
            } finally {
                finishLoad.countDown();
            }
            for (var result : results) assertEquals("body", result.get(5, TimeUnit.SECONDS));
        }
        assertEquals(1, loads.get());
        assertEquals(1, writes.get());
        assertTrue(locks.isEmpty());
        verify(values, atLeastOnce()).setIfAbsent(anyString(), anyString(), eq(Duration.ofSeconds(30)));
    }

    @Test void checksCacheAgainAfterAcquiringLock() {
        Supplier<String> read = mock(Supplier.class);
        Supplier<String> load = mock(Supplier.class);
        when(read.get()).thenReturn(null, "filled-before-lock");
        assertEquals("filled-before-lock", mutex.getOrLoad("article:1", read, load, value -> fail()));
        verifyNoInteractions(load);
        assertTrue(locks.isEmpty());
    }

    @Test void waiterReadsOwnersResultWithoutLoading() {
        locks.put("article:1:rebuild-lock", "other-owner");
        Supplier<String> read = mock(Supplier.class);
        Supplier<String> load = mock(Supplier.class);
        when(read.get()).thenReturn(null, "owner-result");
        assertEquals("owner-result", mutex.getOrLoad("article:1", read, load, value -> fail()));
        verifyNoInteractions(load);
        assertEquals("other-owner", locks.get("article:1:rebuild-lock"));
    }

    @Test void timeoutDoesNotFallThroughToDatabase() {
        locks.put("article:1:rebuild-lock", "other-owner");
        Supplier<String> load = mock(Supplier.class);
        var noWait = new CacheRebuildMutex(redis, 30000, 0);
        var error = assertThrows(BusinessException.class,
                () -> noWait.getOrLoad("article:1", () -> null, load, value -> fail()));
        assertEquals(503, error.getCode());
        verifyNoInteractions(load);
    }

    @Test void loaderFailureReleasesLockAndNextRequestCanRetry() {
        var missing = new BusinessException(404, "missing");
        assertSame(missing, assertThrows(BusinessException.class, () -> mutex.getOrLoad("article:1",
                () -> null, () -> { throw missing; }, value -> fail())));
        assertTrue(locks.isEmpty());
        assertEquals("retry", mutex.getOrLoad("article:1", () -> null, () -> "retry", value -> {}));
    }

    @Test void expiredOwnerNeitherPublishesNorDeletesSuccessorsLock() {
        assertEquals("old-result", mutex.getOrLoad("article:1", () -> null, () -> {
            locks.put("article:1:rebuild-lock", "new-owner");
            return "old-result";
        }, value -> fail("Expired owner must not publish")));
        assertEquals("new-owner", locks.get("article:1:rebuild-lock"));
    }

    @Test void failedReleaseDoesNotMaskTheOriginalLoaderFailure() {
        when(redis.execute(any(DefaultRedisScript.class), anyList(), anyString()))
                .thenThrow(new IllegalStateException("Redis unavailable"));
        var missing = new BusinessException(404, "missing");
        assertSame(missing, assertThrows(BusinessException.class, () -> mutex.getOrLoad("article:1",
                () -> null, () -> { throw missing; }, value -> fail())));
    }

    @Test void interruptedWaiterExitsWithoutQueryingDatabase() {
        locks.put("article:1:rebuild-lock", "other-owner");
        Supplier<String> load = mock(Supplier.class);
        Thread.currentThread().interrupt();
        try {
            assertEquals(503, assertThrows(BusinessException.class,
                    () -> mutex.getOrLoad("article:1", () -> null, load, value -> fail())).getCode());
            assertTrue(Thread.currentThread().isInterrupted());
            verifyNoInteractions(load);
        } finally {
            Thread.interrupted();
        }
    }
}
