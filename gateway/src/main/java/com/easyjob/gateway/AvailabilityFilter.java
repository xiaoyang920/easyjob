package com.easyjob.gateway;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import reactor.core.publisher.SignalType;

/** No retry filter: chat, approval and publish commands must never be transparently replayed. */
@Component
public class AvailabilityFilter implements GlobalFilter, Ordered {
    private static CircuitBreakerConfig config(Duration halfOpenWait) { return CircuitBreakerConfig.custom()
        .slidingWindowSize(20).minimumNumberOfCalls(10).failureRateThreshold(50)
        .waitDurationInOpenState(Duration.ofSeconds(15)).permittedNumberOfCallsInHalfOpenState(3)
        .maxWaitDurationInHalfOpenState(halfOpenWait)
        .slowCallDurationThreshold(Duration.ofSeconds(340)).slowCallRateThreshold(100).build(); }
    private final CircuitBreaker blog,agent;
    public AvailabilityFilter() {
        this(CircuitBreaker.of("blog",config(Duration.ofSeconds(10))),
            CircuitBreaker.of("agent-execution",config(Duration.ofSeconds(340))));
    }
    AvailabilityFilter(CircuitBreaker blog,CircuitBreaker agent) {
        this.blog=blog;this.agent=agent;
        var log=org.slf4j.LoggerFactory.getLogger(AvailabilityFilter.class);
        for(var breaker:new CircuitBreaker[]{blog,agent}) breaker.getEventPublisher().onStateTransition(event ->
            log.info("gateway_circuit name={} transition={}",event.getCircuitBreakerName(),event.getStateTransition()));
    }
    @Override public int getOrder() { return -100; }
    @Override public Mono<Void> filter(ServerWebExchange exchange,GatewayFilterChain chain) {
        Mono<Void> execution=Mono.defer(() -> chain.filter(exchange)).then(Mono.defer(() -> {
            var status=exchange.getResponse().getStatusCode();
            if (status!=null && status.is5xxServerError()) return Mono.error(new UpstreamFailure());
            return Mono.<Void>empty();
        }));
        String path=exchange.getRequest().getPath().value();
        boolean startsAgent=path.matches("/api/agent/chat(/stream|/resume|/resume/stream)?");
        // Isolate AI failures; keep cancellation available and exclude long-lived sockets.
        if(!path.startsWith("/ws") && (!path.startsWith("/api/agent/") || startsAgent)) {
            var breaker=startsAgent?agent:blog;
            var upstream=execution;
            execution=Mono.defer(() -> {
                if(!breaker.tryAcquirePermission())
                    return EdgeFilter.reject(exchange,HttpStatus.SERVICE_UNAVAILABLE,"服务暂不可用，请稍后重试");
                long started=System.nanoTime();
                var recorded=new AtomicBoolean();
                Consumer<Throwable> finish=error -> {
                    if(!recorded.compareAndSet(false,true)) return;
                    var status=exchange.getResponse().getStatusCode();
                    if(error==null && status!=null && status.is5xxServerError()) error=new UpstreamFailure();
                    if(error==null) breaker.onSuccess(System.nanoTime()-started,TimeUnit.NANOSECONDS);
                    else breaker.onError(System.nanoTime()-started,TimeUnit.NANOSECONDS,error);
                };
                // SSE may stay open for hours. Its response headers establish
                // upstream availability; body completion must not hold a
                // half-open probe and lock every ordinary API out indefinitely.
                exchange.getResponse().beforeCommit(() -> { finish.accept(null);return Mono.empty(); });
                return upstream.doOnSuccess(ignored -> finish.accept(null))
                    .doOnError(finish)
                    .doFinally(signal -> {
                        if(signal==SignalType.CANCEL && recorded.compareAndSet(false,true)) breaker.releasePermission();
                    });
            });
        }
        return execution.onErrorResume(error -> exchange.getResponse().isCommitted()?Mono.empty():
                EdgeFilter.reject(exchange,HttpStatus.SERVICE_UNAVAILABLE,"服务暂不可用，请稍后重试"));
    }
    static class UpstreamFailure extends RuntimeException {}
}
