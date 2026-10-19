package com.easyjob.gateway;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.ArrayList;
import static org.junit.jupiter.api.Assertions.*;

class AvailabilityFilterTests {
    CircuitBreaker breaker(String name) {
        return CircuitBreaker.of(name,CircuitBreakerConfig.custom().minimumNumberOfCalls(10)
            .permittedNumberOfCallsInHalfOpenState(3).maxWaitDurationInHalfOpenState(Duration.ofSeconds(10)).build());
    }
    @Test void liveSseHeadersCompleteHalfOpenProbesWhileBodiesStayOpen() {
        var blog=breaker("blog");var agent=breaker("agent");
        var filter=new AvailabilityFilter(blog,agent);
        blog.transitionToOpenState();blog.transitionToHalfOpenState();
        var streams=new ArrayList<Disposable>();
        try {
            for(int i=0;i<3;i++) {
                var exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/online/events").accept(MediaType.TEXT_EVENT_STREAM));
                streams.add(filter.filter(exchange,request -> {
                    request.getResponse().getHeaders().setContentType(MediaType.TEXT_EVENT_STREAM);
                    var first=request.getResponse().bufferFactory().wrap("data:online\n\n".getBytes());
                    return request.getResponse().writeWith(Flux.concat(Mono.just(first),Flux.never()));
                }).subscribe());
                assertTrue(exchange.getResponse().isCommitted());
                assertFalse(streams.getLast().isDisposed());
            }
            assertEquals(CircuitBreaker.State.CLOSED,blog.getState());
            var ordinary=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list"));
            filter.filter(ordinary,request -> request.getResponse().setComplete()).block(Duration.ofSeconds(1));
            assertNotEquals(HttpStatus.SERVICE_UNAVAILABLE,ordinary.getResponse().getStatusCode());
        } finally { streams.forEach(Disposable::dispose); }
    }
    @Test void cancelledProbeBeforeHeadersReleasesItsSlotAndDoesNotCountAsBackendFailure() {
        var blog=breaker("blog");var agent=breaker("agent");
        blog.transitionToOpenState();blog.transitionToHalfOpenState();
        var filter=new AvailabilityFilter(blog,agent);
        for(int i=0;i<10;i++) {
            var exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list"));
            var subscription=filter.filter(exchange,request -> Mono.never()).subscribe();
            assertFalse(subscription.isDisposed());
            subscription.dispose();
        }
        assertEquals(0,blog.getMetrics().getNumberOfFailedCalls());
        assertEquals(0,blog.getMetrics().getNumberOfNotPermittedCalls());
    }
    @Test void failuresAreCountedOnceAndCommandsAreNeverRetried() {
        var blog=breaker("blog");var agent=breaker("agent");
        var filter=new AvailabilityFilter(blog,agent);
        var calls=new java.util.concurrent.atomic.AtomicInteger();
        var exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/article/create"));
        filter.filter(exchange,request -> {
            calls.incrementAndGet();return Mono.error(new IllegalStateException("upstream unavailable"));
        }).block(Duration.ofSeconds(1));
        assertEquals(1,calls.get());
        assertEquals(1,blog.getMetrics().getNumberOfFailedCalls());
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE,exchange.getResponse().getStatusCode());
    }
    @Test void committedUpstream5xxIsCountedOnceAndStopBypassesBothBreakers() {
        var blog=breaker("blog");var agent=breaker("agent");
        var filter=new AvailabilityFilter(blog,agent);
        var failed=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list"));
        filter.filter(failed,request -> {
            request.getResponse().setStatusCode(HttpStatus.BAD_GATEWAY);
            return request.getResponse().setComplete();
        }).block(Duration.ofSeconds(1));
        assertEquals(1,blog.getMetrics().getNumberOfFailedCalls());
        blog.transitionToOpenState();agent.transitionToOpenState();
        var cancel=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/42/cancel"));
        filter.filter(cancel,request -> request.getResponse().setComplete()).block(Duration.ofSeconds(1));
        assertNotEquals(HttpStatus.SERVICE_UNAVAILABLE,cancel.getResponse().getStatusCode());
    }
}
