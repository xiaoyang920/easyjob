package com.easyjob.gateway;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.core.Ordered;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

/** Edge admission only. Java remains authoritative for session revocation and business permissions. */
@Component
public class EdgeFilter implements GlobalFilter, Ordered {
    private static final DefaultRedisScript<Long> LIMIT = new DefaultRedisScript<>("""
        local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end
        if n>tonumber(ARGV[1]) then return 0 end; return 1
        """, Long.class);
    private final ReactiveStringRedisTemplate redis;
    private final javax.crypto.SecretKey key;
    private final int apiLimit, authLimit, aiLimit;
    public EdgeFilter(ReactiveStringRedisTemplate redis, @Value("${easyjob.jwt.secret-key}") String secret,
            @Value("${easyjob.gateway.api-per-minute:300}") int api,
            @Value("${easyjob.gateway.auth-per-minute:20}") int auth,
            @Value("${easyjob.gateway.ai-per-minute:12}") int ai) {
        this.redis=redis; key=Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        apiLimit=api;authLimit=auth;aiLimit=ai;
        if (secret.getBytes(StandardCharsets.UTF_8).length<64 || api<1 || auth<1 || ai<1)
            throw new IllegalArgumentException("Gateway JWT / rate limit configuration invalid");
    }
    @Override public int getOrder() { return -200; }
    @Override public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String path=exchange.getRequest().getPath().value();
        if (path.startsWith("/internal") || path.startsWith("/actuator"))
            return reject(exchange,HttpStatus.NOT_FOUND,"接口不存在");
        String bearer=exchange.getRequest().getHeaders().getFirst("Authorization");
        String token=bearer!=null && bearer.startsWith("Bearer ")?bearer.substring(7):null;
        if (token==null && (path.startsWith("/ws") || path.startsWith("/api/agent")))
            token=exchange.getRequest().getQueryParams().getFirst("token");
        String uid=null;
        // Expired access tokens must not prevent refresh/logout using the refresh cookie.
        if (token!=null && !path.startsWith("/api/auth/")) {
            try {
                var jwt=Jwts.parserBuilder().setSigningKey(key).build().parseClaimsJws(token);
                if (!"HS512".equals(jwt.getHeader().getAlgorithm())) throw new IllegalArgumentException();
                long id=((Number)jwt.getBody().get("userId")).longValue();
                if (id<=0 || jwt.getBody().getExpiration()==null) throw new IllegalArgumentException();
                uid=Long.toString(id);
            } catch (RuntimeException error) { return reject(exchange,HttpStatus.UNAUTHORIZED,"登录已过期，请重新登录"); }
        }
        var request=exchange.getRequest().mutate().headers(headers -> {
            headers.keySet().removeIf(name -> name.toLowerCase(java.util.Locale.ROOT).startsWith("x-agent-")
                || name.equalsIgnoreCase("X-User-Id") || name.equalsIgnoreCase("X-Service-Key")
                || name.equalsIgnoreCase("X-Gateway-User") || name.toLowerCase(java.util.Locale.ROOT).startsWith("x-forwarded-")
                || name.equalsIgnoreCase("Forwarded"));
            headers.set("X-Request-Id",UUID.randomUUID().toString());
        }).build();
        var clean=exchange.mutate().request(request).build();
        if (path.startsWith("/uploads/")) return chain.filter(clean);
        String ip=exchange.getRequest().getRemoteAddress()==null?"unknown":exchange.getRequest().getRemoteAddress().getAddress().getHostAddress();
        String principal=uid==null?"ip:"+ip:"user:"+uid;
        String bucket=path.startsWith("/api/auth/")?"auth":"api";
        int limit=bucket.equals("auth")?authLimit:apiLimit;
        // Stop/status/reconnect use the general budget so an exhausted AI budget cannot trap a running task.
        boolean aiStart=path.matches("/api/agent/chat(/stream|/resume|/resume/stream)?");
        Mono<Boolean> admitted=allow(bucket,principal,limit);
        if (aiStart) admitted=admitted.flatMap(ok -> ok?allow("ai",principal,aiLimit):Mono.just(false));
        return admitted.switchIfEmpty(Mono.error(new IllegalStateException("Empty limiter result")))
            .flatMap(ok -> ok?chain.filter(clean):reject(clean,HttpStatus.TOO_MANY_REQUESTS,"请求过于频繁，请稍后重试"))
            .onErrorResume(error -> reject(clean,HttpStatus.SERVICE_UNAVAILABLE,"请求校验服务暂不可用"));
    }
    private Mono<Boolean> allow(String bucket,String principal,int limit) {
        String digest;
        try { digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(principal.getBytes(StandardCharsets.UTF_8))); }
        catch (Exception e) { return Mono.error(e); }
        return redis.execute(LIMIT,List.of("gateway:limit:"+bucket+":"+digest),List.of(Integer.toString(limit)))
            .next().map(value -> value==1);
    }
    static Mono<Void> reject(ServerWebExchange exchange,HttpStatus status,String message) {
        if (exchange.getResponse().isCommitted()) return Mono.empty();
        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        if (status==HttpStatus.TOO_MANY_REQUESTS) exchange.getResponse().getHeaders().set("Retry-After","60");
        byte[] body=("{\"code\":"+status.value()+",\"message\":\""+message+"\",\"data\":null}").getBytes(StandardCharsets.UTF_8);
        return exchange.getResponse().writeWith(Mono.just(exchange.getResponse().bufferFactory().wrap(body)));
    }
}
