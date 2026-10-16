package com.easyjob.service.impl;

import com.alibaba.fastjson2.JSON;
import com.easyjob.dto.NotificationMessage;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Map;
import java.util.Set;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

@Service
@Slf4j
public class SseEmitterService {
    /** A tab owns its emitter; opening another tab must not close this one. */
    private final ConcurrentHashMap<Long, Set<SseEmitter>> emitters = new ConcurrentHashMap<>();

    /** 心跳线程池（每 25s 发一次注释消息，防止 Nginx/代理 60s 空闲断连） */
    private ScheduledExecutorService heartbeatExecutor;

    @PostConstruct
    public void init() {
        heartbeatExecutor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "sse-heartbeat");
            t.setDaemon(true);
            return t;
        });
        heartbeatExecutor.scheduleAtFixedRate(this::heartbeat, 25, 25, TimeUnit.SECONDS);
    }

    @PreDestroy
    public void shutdown() {
        if (heartbeatExecutor != null) {
            heartbeatExecutor.shutdown();
        }
        emitters.values().forEach(group -> List.copyOf(group).forEach(e -> {
            try { e.complete(); } catch (Exception ignore) {}
        }));
        emitters.clear();
    }

    /**
     * 建立 SSE 连接
     */
    public SseEmitter connect(Long userId) {
        // 超时 30 分钟；前端 EventSource 会自动重连
        SseEmitter emitter = newEmitter();

        // 回调里用"只有当前持有的 emitter 与自己相同时才清理"避免被重连覆盖时误删
        emitter.onCompletion(() -> removeIfSame(userId, emitter));
        emitter.onTimeout(() -> removeIfSame(userId, emitter));
        emitter.onError(e -> removeIfSame(userId, emitter));

        emitters.compute(userId, (id, group) -> {
            if (group == null) group = ConcurrentHashMap.newKeySet();
            if (group.size() >= 32) throw new com.easyjob.exception.BusinessException(429,"通知连接过多，请关闭不使用的页面");
            group.add(emitter);
            return group;
        });

        // 连接建立后立刻发一个握手事件，让前端尽快收到 open
        try {
            emitter.send(SseEmitter.event().name("connected").data("ok"));
        } catch (Exception e) {
            log.warn("SSE 握手事件发送失败: userId={}", userId, e);
            removeIfSame(userId, emitter);
        }

        log.info("SSE 连接建立: userId={}, 当前在线={}", userId, emitters.size());
        return emitter;
    }

    protected SseEmitter newEmitter() { return new SseEmitter(30 * 60 * 1000L); }

    /**
     * 推送通知给指定用户（不在线则跳过）
     */
    public void sendToUser(Long userId, NotificationMessage msg) {
        Set<SseEmitter> group = emitters.get(userId);
        if (group == null) {
            log.debug("用户 {} 不在线，跳过推送", userId);
            return;
        }
        for (SseEmitter emitter : List.copyOf(group)) try {
            emitter.send(SseEmitter.event()
                    .name("notification")
                    .data(JSON.toJSONString(msg,com.alibaba.fastjson2.JSONWriter.Feature.WriteLongAsString))
            );
        } catch (Exception e) {
            log.warn("SSE 推送失败，移除连接: userId={}, err={}", userId, e.getMessage());
            dropEmitter(userId, emitter, e);
        }
    }

    /**
     * 主动断开指定用户的连接
     */
    public void disconnect(Long userId) {
        Set<SseEmitter> removed = emitters.remove(userId);
        if (removed != null) {
            for (SseEmitter emitter : List.copyOf(removed)) try {
                emitter.complete();
            } catch (Exception ignore) {
            }
        }
        log.info("SSE 断开连接: userId={}, 当前在线={}", userId, emitters.size());
    }

    /**
     * 心跳：向所有连接发一个注释行（以 ":" 开头，SSE 协议中的 comment，前端会忽略）
     *
     * 双层兜底：
     * - 内层 catch Exception：单个 emitter send 失败时走 dropEmitter 清理死连接
     *   （覆盖 IOException / AsyncRequestNotUsableException / IllegalStateException 等所有可能类型）
     * - 外层 catch Throwable：防止 ScheduledThreadPoolExecutor.scheduleAtFixedRate 因未捕获异常
     *   静默取消后续调度（Javadoc: "If any execution of this task throws an exception,
     *   subsequent executions are suppressed"）
     */
    private void heartbeat() {
        try {
            if (emitters.isEmpty()) return;
            int before = emitters.size();
            for (Map.Entry<Long, Set<SseEmitter>> e : emitters.entrySet()) {
                Long userId = e.getKey();
                for (SseEmitter emitter : List.copyOf(e.getValue())) try {
                    emitter.send(SseEmitter.event().comment("keep-alive"));
                } catch (Exception ex) {
                    log.debug("心跳失败，清理连接: userId={}, err={}", userId, ex.getClass().getSimpleName());
                    dropEmitter(userId, emitter, ex);
                }
            }
            log.debug("心跳完成，在线={} → {}", before, emitters.size());
        } catch (Throwable t) {
            // 外层兜底：吞掉任意未知异常保证心跳调度永不停机
            log.error("心跳任务整体异常（已吞掉，调度继续）", t);
        }
    }

    /**
     * 仅当 map 里存的还是同一个 emitter 时才移除（解决重连覆盖场景的误删）
     */
    private void removeIfSame(Long userId, SseEmitter target) {
        emitters.computeIfPresent(userId, (id, group) -> {
            group.remove(target);
            return group.isEmpty() ? null : group;
        });
    }

    /**
     * 发送失败/心跳失败时的清理：移除 + completeWithError 避免资源泄漏
     */
    private void dropEmitter(Long userId, SseEmitter emitter, Throwable cause) {
        removeIfSame(userId, emitter);
            try {
                emitter.completeWithError(cause);
            } catch (Exception ignore) {
            }
    }
}
