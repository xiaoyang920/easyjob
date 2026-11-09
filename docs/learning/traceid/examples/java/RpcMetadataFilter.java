package com.easyjob.observability;

import com.easyjob.rpc.v1.Reply;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import org.apache.dubbo.common.extension.Activate;
import org.apache.dubbo.rpc.Filter;
import org.apache.dubbo.rpc.AppResponse;
import org.apache.dubbo.rpc.Invocation;
import org.apache.dubbo.rpc.Invoker;
import org.apache.dubbo.rpc.Result;
import org.apache.dubbo.rpc.RpcException;
import org.apache.dubbo.rpc.model.MethodDescriptor;
import org.apache.dubbo.rpc.model.ServiceModel;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Activate(group = {"consumer", "provider"})
public final class RpcMetadataFilter implements Filter {
    private static final List<String> KEYS = List.of("traceparent", "tracestate");

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        if (!"tri".equals(invoker.getUrl().getProtocol())) {
            return invoker.invoke(invocation);
        }
        String side = invoker.getUrl().getParameter("side");
        if ("consumer".equals(side)) {
            // Callers use TracingAgentRpc.wrap(...) to activate a CLIENT span.
            Map<String, String> carrier = TraceSupport.inject();
            for (String key : KEYS) {
                invocation.getObjectAttachments().remove(key);
                String value = carrier.get(key);
                if (value != null) invocation.setAttachment(key, value);
            }
            // Triple serializes string attachments into HTTP/2 metadata.
            return invoker.invoke(invocation);
        }
        if (!"provider".equals(side)) {
            return invoker.invoke(invocation);
        }

        // This provider wrapper supports unary results, not stream lifetimes.
        ServiceModel model = invocation.getServiceModel();
        if (model == null) model = invoker.getUrl().getServiceModel();
        if (model != null) {
            MethodDescriptor descriptor = model.getServiceModel()
                .getMethod(invocation.getMethodName(), invocation.getParameterTypes());
            if (descriptor != null && descriptor.getRpcType() != MethodDescriptor.RpcType.UNARY) {
                return invoker.invoke(invocation);
            }
        }

        Map<String, String> carrier = new HashMap<>();
        for (String key : KEYS) {
            String value = invocation.getAttachment(key);
            if (value != null) carrier.put(key, value);
        }
        String rpcService = invoker.getInterface().getName();
        String rpcMethod = invocation.getMethodName();
        Span span = TraceSupport.receive(rpcService + "/" + rpcMethod, SpanKind.SERVER, carrier);
        span.setAttribute("rpc.system", "grpc");
        span.setAttribute("rpc.service", rpcService);
        span.setAttribute("rpc.method", rpcMethod);
        try (Scope scope = span.makeCurrent()) {
            Result result = invoker.invoke(invocation);
            if (result instanceof AppResponse) {
                // Already completed: AppResponse does not support completion callbacks.
                try { recordResult(span, result, null); }
                finally { span.end(); }
                return result;
            }
            // Wait for the actual unary result, including asynchronous results.
            return result.whenCompleteWithContext((completed, failure) -> {
                try { recordResult(span, completed, failure); }
                finally { span.end(); }
            });
        } catch (RuntimeException | Error failure) {
            TraceSupport.failure(span, failure);
            span.end();
            throw failure;
        }
    }

    private static void recordResult(Span span, Result result, Throwable failure) {
        if (failure != null) TraceSupport.failure(span, failure);
        else if (result.hasException()) TraceSupport.failure(span, result.getException());
        else if (result.getValue() instanceof Reply reply) {
            TraceSupport.businessStatus(span, reply.hasError() ? reply.getError().getStatus() : 200);
        }
    }
}
