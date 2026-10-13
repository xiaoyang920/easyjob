package com.easyjob.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class EdgeFilterTests {
    static final String SECRET="gateway-offline-test-secret-64-bytes-minimum-012345678901234567890123456789";
    @SuppressWarnings("unchecked") ReactiveStringRedisTemplate redis(long allowed) {
        var redis=mock(ReactiveStringRedisTemplate.class);
        when(redis.execute(any(),anyList(),anyList())).thenReturn((Flux)Flux.just(allowed));return redis;
    }
    @Test void stripsForgedIdentityAndForwardingHeadersBeforeRouting() {
        var redis=redis(1);var edge=new EdgeFilter(redis,SECRET,300,20,12);
        var request=MockServerHttpRequest.get("/api/article/list").header("X-Agent-Key","forged").header("X-Agent-User","1")
            .header("X-User-Id","1").header("X-Forwarded-For","1.2.3.4").build();
        GatewayFilterChain chain=exchange -> {
            assertNull(exchange.getRequest().getHeaders().getFirst("X-Agent-Key"));
            assertNull(exchange.getRequest().getHeaders().getFirst("X-User-Id"));
            assertNull(exchange.getRequest().getHeaders().getFirst("X-Forwarded-For"));
            assertNotNull(exchange.getRequest().getHeaders().getFirst("X-Request-Id"));
            return exchange.getResponse().setComplete();
        };
        edge.filter(MockServerWebExchange.from(request),chain).block();
        verify(redis,times(1)).execute(any(),anyList(),anyList());
    }
    @Test void invalidTokenAndInternalPathsNeverReachBackend() {
        var redis=redis(1);var filter=new EdgeFilter(redis,SECRET,300,20,12);var chain=mock(GatewayFilterChain.class);
        var bad=MockServerWebExchange.from(MockServerHttpRequest.get("/api/agent/conversations").header("Authorization","Bearer invalid"));
        filter.filter(bad,chain).block();assertEquals(HttpStatus.UNAUTHORIZED,bad.getResponse().getStatusCode());
        var internal=MockServerWebExchange.from(MockServerHttpRequest.get("/internal/agent/drafts"));
        filter.filter(internal,chain).block();assertEquals(HttpStatus.NOT_FOUND,internal.getResponse().getStatusCode());
        verifyNoInteractions(chain,redis);
    }
    @Test void rateLimitReturns429AndDoesNotInvokeBusinessAction() {
        var redis=redis(0);var filter=new EdgeFilter(redis,SECRET,300,20,12);var chain=mock(GatewayFilterChain.class);
        var exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat"));
        filter.filter(exchange,chain).block();assertEquals(HttpStatus.TOO_MANY_REQUESTS,exchange.getResponse().getStatusCode());
        assertEquals("60",exchange.getResponse().getHeaders().getFirst("Retry-After"));verifyNoInteractions(chain);
    }
    @Test void refreshIgnoresExpiredAccessTokenAndRetainsCookie() {
        var redis=redis(1);var filter=new EdgeFilter(redis,SECRET,300,20,12);
        var exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/auth/refresh").header("Authorization","Bearer expired").header("Cookie","refresh=opaque"));
        filter.filter(exchange,e -> {assertEquals("refresh=opaque",e.getRequest().getHeaders().getFirst("Cookie"));return e.getResponse().setComplete();}).block();
    }
    @Test void stopDoesNotSpendAiStartBudget() {
        var redis=redis(1);var filter=new EdgeFilter(redis,SECRET,300,20,12);
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/11/cancel")),e -> e.getResponse().setComplete()).block();
        verify(redis,times(1)).execute(any(),anyList(),anyList());
    }
    @Test void redisFailureFailsClosedWithoutRunningMutation() {
        var redis=redis(1);when(redis.execute(any(),anyList(),anyList())).thenReturn(Flux.error(new IllegalStateException("offline")));
        var filter=new EdgeFilter(redis,SECRET,300,20,12);var chain=mock(GatewayFilterChain.class);
        var exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/article/create"));
        filter.filter(exchange,chain).block();assertEquals(HttpStatus.SERVICE_UNAVAILABLE,exchange.getResponse().getStatusCode());verifyNoInteractions(chain);
    }
    @Test void aiCircuitDoesNotBlockArticleReadOrCancel() {
        var filter=new AvailabilityFilter();var failed=mock(GatewayFilterChain.class);
        when(failed.filter(any())).thenReturn(Mono.error(new IllegalStateException("unavailable")));
        for(int i=0;i<12;i++)filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat")),failed).block();
        verify(failed,times(10)).filter(any());
        var healthy=mock(GatewayFilterChain.class);when(healthy.filter(any())).thenReturn(Mono.empty());
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list")),healthy).block();
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/11/cancel")),healthy).block();
        verify(healthy,times(2)).filter(any());
    }
    @Test void breakerStopsCallingUnavailableBackendWithoutRetryingCommands() {
        var filter=new AvailabilityFilter();var chain=mock(GatewayFilterChain.class);when(chain.filter(any())).thenReturn(Mono.error(new IllegalStateException("offline")));
        for(int i=0;i<12;i++) {
            var exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat"));
            filter.filter(exchange,chain).block();assertEquals(HttpStatus.SERVICE_UNAVAILABLE,exchange.getResponse().getStatusCode());
        }
        verify(chain,times(10)).filter(any());
    }
}
