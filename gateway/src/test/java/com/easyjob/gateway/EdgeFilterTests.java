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
    @Test void statusPollingCannotExhaustTheBudgetForBusinessActions() {
        ReactiveStringRedisTemplate redis=redis(1);
        when(redis.execute(any(),anyList(),anyList())).thenAnswer(call->{
            List<String> keys=call.getArgument(1);return Flux.just(keys.getFirst().startsWith("gateway:limit:observe:")?0L:1L);
        });
        EdgeFilter edge=new EdgeFilter(redis,SECRET,300,20,12);
        MockServerWebExchange polling=MockServerWebExchange.from(MockServerHttpRequest.get("/api/agent/run-overview"));
        GatewayFilterChain rejected=mock(GatewayFilterChain.class);edge.filter(polling,rejected).block();
        assertEquals(HttpStatus.TOO_MANY_REQUESTS,polling.getResponse().getStatusCode());verifyNoInteractions(rejected);
        GatewayFilterChain action=mock(GatewayFilterChain.class);when(action.filter(any())).thenReturn(Mono.empty());
        edge.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/article/create")),action).block();verify(action).filter(any());
    }
    @Test void notificationStreamUsesItsAuthenticatedUsersReconnectBudget() {
        String token=io.jsonwebtoken.Jwts.builder().claim("userId",7L).setExpiration(new java.util.Date(System.currentTimeMillis()+60000))
                .signWith(io.jsonwebtoken.security.Keys.hmacShaKeyFor(SECRET.getBytes(java.nio.charset.StandardCharsets.UTF_8)),io.jsonwebtoken.SignatureAlgorithm.HS512).compact();
        ReactiveStringRedisTemplate redis=redis(1);EdgeFilter edge=new EdgeFilter(redis,SECRET,300,20,12);
        edge.filter(MockServerWebExchange.from(MockServerHttpRequest.get("/api/notification/stream?token="+token)),e->Mono.empty()).block();
        verify(redis).execute(any(),argThat(keys->keys.getFirst().toString().startsWith("gateway:limit:stream:")),eq(List.of("30")));
    }
    static final String SECRET="gateway-offline-test-secret-64-bytes-minimum-012345678901234567890123456789";
    @SuppressWarnings("unchecked") ReactiveStringRedisTemplate redis(long allowed) {
        ReactiveStringRedisTemplate redis=mock(ReactiveStringRedisTemplate.class);
        when(redis.execute(any(),anyList(),anyList())).thenReturn((Flux)Flux.just(allowed));return redis;
    }
    @Test void stripsForgedIdentityAndForwardingHeadersBeforeRouting() {
        ReactiveStringRedisTemplate redis=redis(1);EdgeFilter edge=new EdgeFilter(redis,SECRET,300,20,12);
        MockServerHttpRequest request=MockServerHttpRequest.get("/api/article/list").header("X-Agent-Key","forged").header("X-Agent-User","1")
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
        ReactiveStringRedisTemplate redis=redis(1);EdgeFilter filter=new EdgeFilter(redis,SECRET,300,20,12);GatewayFilterChain chain=mock(GatewayFilterChain.class);
        MockServerWebExchange bad=MockServerWebExchange.from(MockServerHttpRequest.get("/api/agent/conversations").header("Authorization","Bearer invalid"));
        filter.filter(bad,chain).block();assertEquals(HttpStatus.UNAUTHORIZED,bad.getResponse().getStatusCode());
        MockServerWebExchange internal=MockServerWebExchange.from(MockServerHttpRequest.get("/internal/agent/drafts"));
        filter.filter(internal,chain).block();assertEquals(HttpStatus.NOT_FOUND,internal.getResponse().getStatusCode());
        verifyNoInteractions(chain,redis);
    }
    @Test void rateLimitReturns429AndDoesNotInvokeBusinessAction() {
        ReactiveStringRedisTemplate redis=redis(0);EdgeFilter filter=new EdgeFilter(redis,SECRET,300,20,12);GatewayFilterChain chain=mock(GatewayFilterChain.class);
        MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat"));
        filter.filter(exchange,chain).block();assertEquals(HttpStatus.TOO_MANY_REQUESTS,exchange.getResponse().getStatusCode());
        assertEquals("60",exchange.getResponse().getHeaders().getFirst("Retry-After"));verifyNoInteractions(chain);
    }
    @Test void refreshIgnoresExpiredAccessTokenAndRetainsCookie() {
        ReactiveStringRedisTemplate redis=redis(1);EdgeFilter filter=new EdgeFilter(redis,SECRET,300,20,12);
        MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/auth/refresh").header("Authorization","Bearer expired").header("Cookie","refresh=opaque"));
        filter.filter(exchange,e -> {assertEquals("refresh=opaque",e.getRequest().getHeaders().getFirst("Cookie"));return e.getResponse().setComplete();}).block();
    }
    @Test void stopDoesNotSpendAiStartBudget() {
        ReactiveStringRedisTemplate redis=redis(1);EdgeFilter filter=new EdgeFilter(redis,SECRET,300,20,12);
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/11/cancel")),e -> e.getResponse().setComplete()).block();
        verify(redis,times(1)).execute(any(),anyList(),anyList());
    }
    @Test void redisFailureFailsClosedWithoutRunningMutation() {
        ReactiveStringRedisTemplate redis=redis(1);when(redis.execute(any(),anyList(),anyList())).thenReturn(Flux.error(new IllegalStateException("offline")));
        EdgeFilter filter=new EdgeFilter(redis,SECRET,300,20,12);GatewayFilterChain chain=mock(GatewayFilterChain.class);
        MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/article/create"));
        filter.filter(exchange,chain).block();assertEquals(HttpStatus.SERVICE_UNAVAILABLE,exchange.getResponse().getStatusCode());verifyNoInteractions(chain);
    }
    @Test void aiCircuitDoesNotBlockArticleReadOrCancel() {
        AvailabilityFilter filter=new AvailabilityFilter();GatewayFilterChain failed=mock(GatewayFilterChain.class);
        when(failed.filter(any())).thenReturn(Mono.error(new IllegalStateException("unavailable")));
        for(int i=0;i<12;i++)filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat")),failed).block();
        verify(failed,times(10)).filter(any());
        GatewayFilterChain healthy=mock(GatewayFilterChain.class);when(healthy.filter(any())).thenReturn(Mono.empty());
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list")),healthy).block();
        filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/11/cancel")),healthy).block();
        verify(healthy,times(2)).filter(any());
    }
    @Test void breakerStopsCallingUnavailableBackendWithoutRetryingCommands() {
        AvailabilityFilter filter=new AvailabilityFilter();GatewayFilterChain chain=mock(GatewayFilterChain.class);when(chain.filter(any())).thenReturn(Mono.error(new IllegalStateException("offline")));
        for(int i=0;i<12;i++) {
            MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat"));
            filter.filter(exchange,chain).block();assertEquals(HttpStatus.SERVICE_UNAVAILABLE,exchange.getResponse().getStatusCode());
        }
        verify(chain,times(10)).filter(any());
    }
}
