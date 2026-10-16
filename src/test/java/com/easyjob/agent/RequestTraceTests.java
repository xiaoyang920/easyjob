package com.easyjob.agent;

import com.easyjob.observability.*;
import com.easyjob.agent.security.AgentServiceAuth;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.*;
import static org.junit.jupiter.api.Assertions.*;

class RequestTraceTests {
    @Test void rpcIdentityCarriesTraceAndScopesRestorePreviousContext() {
        MDC.put("trace_id","outer-trace");
        try {
            try(var trace=new RequestTrace("inner-trace","run-12345678")) {
                var identity=new AgentServiceAuth("a".repeat(32)).identity(7L);
                assertEquals("inner-trace",identity.getTraceId());assertEquals("run-12345678",MDC.get("run_id"));
            }
            assertEquals("outer-trace",MDC.get("trace_id"));assertNull(MDC.get("run_id"));
        } finally { MDC.clear(); }
    }
    @Test void invalidIncomingTraceCannotInjectLogs() {
        try(var trace=new RequestTrace("bad\ncredential",null)) {
            assertTrue(RequestTrace.valid(RequestTrace.current()));assertFalse(RequestTrace.current().contains("credential"));
        }
    }
    @Test void httpResponseAndRpcIdentityShareCorrelationAndDoNotLeakAfterRequest() throws Exception {
        var request=new MockHttpServletRequest("GET","/api/article/list");request.addHeader("X-Request-Id","gateway-12345678");
        var response=new MockHttpServletResponse();
        new RequestTraceFilter().doFilter(request,response,(req,res) -> {
            assertEquals("gateway-12345678",new AgentServiceAuth("a".repeat(32)).identity(7L).getTraceId());
        });
        assertEquals("gateway-12345678",response.getHeader("X-Request-Id"));assertNull(MDC.get("trace_id"));
    }
}
