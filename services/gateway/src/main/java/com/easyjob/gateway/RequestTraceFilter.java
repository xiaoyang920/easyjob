package com.easyjob.gateway;

import org.springframework.cloud.gateway.filter.*;
import org.springframework.core.Ordered;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/** Log only fixed operational fields; URLs can contain login credentials. */
@Component
public class RequestTraceFilter implements GlobalFilter, Ordered {
    private static final org.slf4j.Logger log=org.slf4j.LoggerFactory.getLogger(RequestTraceFilter.class);
    public int getOrder() { return -201; }
    public Mono<Void> filter(ServerWebExchange exchange,GatewayFilterChain chain) {
        long started=System.nanoTime();
        return chain.filter(exchange).doFinally(signal -> log.info("edge_request trace={} method={} status={} signal={} duration_ms={}",
            exchange.getResponse().getHeaders().getFirst("X-Request-Id"),exchange.getRequest().getMethod(),
            exchange.getResponse().getStatusCode(),signal,(System.nanoTime()-started)/1_000_000));
    }
}
