package com.easyjob.observability;

import org.slf4j.MDC;
import java.util.UUID;

/** Correlation only; IDs never authorize a request and request payloads are never logged. */
public final class RequestTrace implements AutoCloseable {
    private final String previousTrace=MDC.get("trace_id"), previousRun=MDC.get("run_id");
    public RequestTrace(String trace, String run) {
        MDC.put("trace_id",valid(trace)?trace:UUID.randomUUID().toString());
        if(valid(run)) MDC.put("run_id",run); else MDC.remove("run_id");
    }
    public static boolean valid(String value) { return value!=null && value.matches("[a-zA-Z0-9_-]{8,64}"); }
    public static String current() {
        var trace=MDC.get("trace_id");return valid(trace)?trace:UUID.randomUUID().toString();
    }
    @Override public void close() {
        restore("trace_id",previousTrace);restore("run_id",previousRun);
    }
    private void restore(String key,String value) { if(value==null) MDC.remove(key);else MDC.put(key,value); }
}
