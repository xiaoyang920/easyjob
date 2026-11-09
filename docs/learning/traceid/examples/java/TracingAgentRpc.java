package com.easyjob.observability;

import com.easyjob.rpc.v1.AgentRpc;
import com.easyjob.rpc.v1.Reply;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.atomic.AtomicBoolean;

/** Unary RPC tracing for the internal administrative/profile query client. */
public final class TracingAgentRpc {
    private TracingAgentRpc() {}

    public static AgentRpc wrap(AgentRpc delegate) {
        return wrap(AgentRpc.class, delegate);
    }

    public static <T> T wrap(Class<T> rpcInterface, T delegate) {
        return rpcInterface.cast(Proxy.newProxyInstance(rpcInterface.getClassLoader(),
            new Class<?>[]{rpcInterface}, (proxy, method, originalArgs) -> {
                Object[] args = originalArgs == null ? new Object[0] : originalArgs;
                if (method.getDeclaringClass() == Object.class) {
                    try { return method.invoke(delegate, args); }
                    catch (InvocationTargetException error) { throw error.getCause(); }
                }
                Span span = TraceSupport.tracer().spanBuilder(rpcInterface.getName() + "/" + method.getName())
                    .setSpanKind(SpanKind.CLIENT).startSpan();
                span.setAttribute("rpc.system", "grpc");
                span.setAttribute("rpc.service", rpcInterface.getName());
                span.setAttribute("rpc.method", method.getName());
                AtomicBoolean ended = new AtomicBoolean();
                Runnable end = () -> { if (ended.compareAndSet(false, true)) span.end(); };
                try (Scope scope = span.makeCurrent()) {
                    Object reply;
                    try { reply = method.invoke(delegate, args); }
                    catch (InvocationTargetException error) { throw error.getCause(); }
                    if (reply instanceof CompletionStage<?> stage) {
                        stage.whenComplete((value, failure) -> {
                            try (Scope callbackScope = span.makeCurrent()) {
                                record(span, value, failure);
                            } finally { end.run(); }
                        });
                    } else {
                        record(span, reply, null);
                        end.run();
                    }
                    return reply;
                } catch (Throwable failure) {
                    TraceSupport.failure(span, failure);
                    end.run();
                    throw failure;
                }
            }));
    }

    private static void record(Span span, Object value, Throwable failure) {
        if (failure != null) TraceSupport.failure(span, failure);
        else if (value instanceof Reply reply)
            TraceSupport.businessStatus(span, reply.hasError() ? reply.getError().getStatus() : 200);
    }
}
