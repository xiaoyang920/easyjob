package com.easyjob.growth;

import com.easyjob.exception.BusinessException;
import com.easyjob.observability.TraceSupport;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;
import java.util.*;
import java.time.Duration;

@Component
public class GrowthReservations {
    final StringRedisTemplate redis;
    final ObjectMapper json;
    private final DefaultRedisScript<List> reserve = new DefaultRedisScript<>();
    private final DefaultRedisScript<Long> release = new DefaultRedisScript<>();
    private final Cache<String, Boolean> sold;

    @org.springframework.beans.factory.annotation.Autowired
    public GrowthReservations(StringRedisTemplate redis, ObjectMapper json) {
        this(redis, json, Caffeine.newBuilder().expireAfterWrite(Duration.ofSeconds(1)).maximumSize(10000).build());
    }

    GrowthReservations(StringRedisTemplate redis, ObjectMapper json, Cache<String, Boolean> sold) {
        this.redis = redis; this.json = json; this.sold = sold;
        reserve.setLocation(new ClassPathResource("growth/reserve.lua")); reserve.setResultType(List.class);
        release.setLocation(new ClassPathResource("growth/release.lua")); release.setResultType(Long.class);
    }

    public String key(String id, String suffix) { return "growth:{" + id + "}:" + suffix; }

    public void prepare(String id, int stock) {
        DefaultRedisScript<Long> script = new DefaultRedisScript<Long>("if redis.call('EXISTS',KEYS[1])==1 then return 1 end; redis.call('SET',KEYS[2],ARGV[2]); redis.call('SET',KEYS[1],ARGV[1]); return 1", Long.class);
        redis.execute(script, List.of(key(id, "ready"), key(id, "stock")), id, Integer.toString(stock));
    }

    public String reserve(String id, long uid, String request, long start, long end, int paySeconds) {
        Span span = TraceSupport.start("growth.reserve", SpanKind.INTERNAL);
        try (Scope scope = span.makeCurrent()) {
            span.setAttribute("easyjob.activity.id", id);
            // Preserve idempotent lookup before the local sold-out shortcut.
            String previous = (String) redis.opsForHash().get(key(id, "users"), Long.toString(uid));
            if (previous != null) {
                span.setAttribute("easyjob.idempotent.hit", true);
                span.setAttribute("easyjob.order.id", previous);
                return previous;
            }
            boolean hit = Boolean.TRUE.equals(sold.getIfPresent(id));
            span.setAttribute("easyjob.sold_cache.hit", hit);
            if (hit) throw new BusinessException(409, "本场套餐已抢完");
            String reservation = UUID.randomUUID().toString();
            span.setAttribute("easyjob.order.id", reservation);
            Map<String, String> carrier = TraceSupport.inject();
            List<?> reply = redis.execute(reserve,
                List.of(key(id, "ready"), key(id, "stock"), key(id, "users"),
                        key(id, "reservations"), key(id, "events"), key(id, "limit:" + uid)),
                id, Long.toString(uid), request, reservation, Long.toString(start), Long.toString(end),
                Integer.toString(paySeconds), carrier.getOrDefault("traceparent", ""), carrier.getOrDefault("tracestate", ""));
            String status = reply == null ? "UNAVAILABLE" : reply.getFirst().toString();
            span.setAttribute("easyjob.reserve.result", status);
            if (status.equals("ACCEPTED")) return reply.get(1).toString();
            if (status.equals("SOLD_OUT")) {
                sold.put(id, Boolean.TRUE); throw new BusinessException(409, "本场套餐已抢完");
            }
            throw new BusinessException(status.equals("LIMITED") ? 429 : status.equals("INACTIVE") ? 409 : 503,
                status.equals("LIMITED") ? "操作太频繁，请稍后重试" : status.equals("INACTIVE") ? "活动尚未开始或已经结束" : "活动正在恢复，请稍后重试");
        } catch (BusinessException error) {
            TraceSupport.businessStatus(span, error.getCode()); throw error;
        } catch (RuntimeException error) {
            TraceSupport.failure(span, error); throw error;
        } finally { span.end(); }
    }

    public Map<String, Object> reservation(String activity, String id) {
        Object raw = redis.opsForHash().get(key(activity, "reservations"), id);
        if (raw == null) return null;
        try { return json.readValue(raw.toString(), new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {}); }
        catch (Exception error) { throw new IllegalStateException("Reservation corrupt", error); }
    }

    public boolean release(String activity, String id) {
        Long ok = redis.execute(release, List.of(key(activity, "ready"), key(activity, "stock"),
                                key(activity, "reservations"), key(activity, "released")), activity, id);
        if (Long.valueOf(1).equals(ok)) { sold.invalidate(activity); return true; }
        return false;
    }
}
