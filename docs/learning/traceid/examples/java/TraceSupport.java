package com.easyjob.observability;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanBuilder;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import java.util.HashMap;
import java.util.Map;

public final class TraceSupport {
    private TraceSupport() {}

    // Resolve lazily: the Java agent owns SDK initialization.
    public static Tracer tracer() {
        return GlobalOpenTelemetry.getTracer("easyjob.business", "1.0");
    }

    public static String currentTraceId() {
        SpanContext context = Span.current().getSpanContext();
        return context.isValid() ? context.getTraceId() : "unavailable";
    }

    public static Map<String, String> inject() {
        Map<String, String> carrier = new HashMap<>();
        GlobalOpenTelemetry.getPropagators().getTextMapPropagator()
            .inject(Context.current(), carrier, Map::put);
        return carrier;
    }

    private static final TextMapGetter<Map<String, String>> GETTER = new TextMapGetter<>() {
        @Override public Iterable<String> keys(Map<String, String> carrier) {
            return carrier.keySet();
        }
        @Override public String get(Map<String, String> carrier, String key) {
            return carrier == null ? null : carrier.get(key);
        }
    };

    public static Context extract(Map<String, String> carrier) {
        // Explicit root prevents a scheduler's unrelated context becoming the parent.
        return GlobalOpenTelemetry.getPropagators().getTextMapPropagator()
            .extract(Context.root(), carrier == null ? Map.of() : carrier, GETTER);
    }

    public static Span start(String name, SpanKind kind) {
        return tracer().spanBuilder(name).setSpanKind(kind).startSpan();
    }

    public static Span receive(String name, SpanKind kind, Map<String, String> carrier) {
        return tracer().spanBuilder(name).setSpanKind(kind)
            .setParent(extract(carrier)).startSpan();
    }

    public static Span linked(String name, Map<String, String> carrier) {
        SpanBuilder builder = tracer().spanBuilder(name).setNoParent();
        SpanContext prior = Span.fromContext(extract(carrier)).getSpanContext();
        if (prior.isValid()) builder.addLink(prior);
        return builder.startSpan();
    }

    public static void failure(Span span, Throwable error) {
        // Free-form exception messages can include SQL values or provider payloads.
        span.setAttribute("error.type", error.getClass().getSimpleName());
        span.setStatus(StatusCode.ERROR);
    }

    public static void businessStatus(Span span, int status) {
        span.setAttribute("easyjob.result.code", status);
        if (status >= 500) span.setStatus(StatusCode.ERROR);
    }
}
