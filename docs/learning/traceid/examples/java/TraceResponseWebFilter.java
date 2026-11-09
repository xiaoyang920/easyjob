package com.easyjob.gateway;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import org.springframework.core.Ordered;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
public class TraceResponseWebFilter implements WebFilter, Ordered {
    @Override public int getOrder() { return Ordered.HIGHEST_PRECEDENCE; }

    @Override public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        return Mono.defer(() -> {
            SpanContext context = Span.current().getSpanContext();
            String id = context.isValid() ? context.getTraceId() : null;
            if (id != null) {
                exchange.getResponse().beforeCommit(() -> {
                    exchange.getResponse().getHeaders().set("X-Trace-Id", id);
                    return Mono.empty();
                });
            }
            return chain.filter(exchange);
        });
    }
}
