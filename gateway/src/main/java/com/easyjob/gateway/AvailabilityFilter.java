package com.easyjob.gateway;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.reactor.circuitbreaker.operator.CircuitBreakerOperator;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.time.Duration;

/** No retry filter: chat, approval and publish commands must never be transparently replayed. */
@Component
public class AvailabilityFilter implements GlobalFilter, Ordered {
    private static final CircuitBreakerConfig CONFIG=CircuitBreakerConfig.custom()
        .slidingWindowSize(20).minimumNumberOfCalls(10).failureRateThreshold(50)
        .waitDurationInOpenState(Duration.ofSeconds(15)).permittedNumberOfCallsInHalfOpenState(3)
        .slowCallDurationThreshold(Duration.ofSeconds(340)).slowCallRateThreshold(100).build();
    private final CircuitBreaker blog=CircuitBreaker.of("blog",CONFIG),agent=CircuitBreaker.of("agent-execution",CONFIG);
    @Override public int getOrder() { return -100; }
    @Override public Mono<Void> filter(ServerWebExchange exchange,GatewayFilterChain chain) {
        // Routing streams directly preserves backpressure, cancellation and heartbeat delivery.
        // Network failures before response commitment still contribute to the breaker.
        Mono<Void> execution=Mono.defer(() -> chain.filter(exchange)).then(Mono.defer(() -> {
            var status=exchange.getResponse().getStatusCode();
            if (status!=null && status.is5xxServerError()) return Mono.error(new UpstreamFailure());
            return Mono.<Void>empty();
        }));
        String path=exchange.getRequest().getPath().value();
        boolean startsAgent=path.matches("/api/agent/chat(/stream|/resume|/resume/stream)?");
        // Isolate AI failures; keep cancellation available and exclude long-lived sockets.
        if(!path.startsWith("/ws") && (!path.startsWith("/api/agent/") || startsAgent))
            execution=execution.transformDeferred(CircuitBreakerOperator.of(startsAgent?agent:blog));
        return execution.onErrorResume(error -> exchange.getResponse().isCommitted()?Mono.empty():
                EdgeFilter.reject(exchange,HttpStatus.SERVICE_UNAVAILABLE,"服务暂不可用，请稍后重试"));
    }
    static class UpstreamFailure extends RuntimeException {}
}
