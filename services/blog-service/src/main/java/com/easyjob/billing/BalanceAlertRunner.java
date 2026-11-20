package com.easyjob.billing;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Dedicated executor keeps network and SMTP latency off business schedulers. */
@Slf4j
public class BalanceAlertRunner {
    private final DeepseekBalanceMonitor monitor;
    private final AtomicBoolean started = new AtomicBoolean();
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable,"deepseek-balance-monitor"); thread.setDaemon(true); return thread;
    });
    public BalanceAlertRunner(DeepseekBalanceMonitor monitor) { this.monitor=monitor; }
    @EventListener(ApplicationReadyEvent.class) public void start() {
        if (!started.compareAndSet(false,true)) return;
        worker.scheduleWithFixedDelay(() -> {
            try { monitor.tick(); }
            catch (Exception error) { log.warn("DeepSeek balance monitor tick failed: {}",error.getClass().getSimpleName()); }
        },0,15,TimeUnit.SECONDS);
        log.info("DeepSeek balance monitor enabled; check and retry times are persisted in MySQL");
    }
    @PreDestroy public void close() { worker.shutdownNow(); }
}
