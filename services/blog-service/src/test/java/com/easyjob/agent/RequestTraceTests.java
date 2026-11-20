package com.easyjob.agent;

import com.easyjob.observability.*;
import com.easyjob.agent.security.AgentServiceAuth;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.*;
import static org.junit.jupiter.api.Assertions.*;
import com.easyjob.observability.RequestTrace;
import com.easyjob.rpc.v1.Identity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class RequestTraceTests {
    @Test void rpcIdentityCarriesTraceAndScopesRestorePreviousContext() {
        MDC.put("trace_id","outer-trace");
        try {
            try(RequestTrace trace=new RequestTrace("inner-trace","run-12345678")) {
                Identity identity=new AgentServiceAuth("a".repeat(32)).identity(7L);
                assertEquals("inner-trace",identity.getTraceId());assertEquals("run-12345678",MDC.get("run_id"));
            }
            assertEquals("outer-trace",MDC.get("trace_id"));assertNull(MDC.get("run_id"));
        } finally { MDC.clear(); }
    }
    @Test void invalidIncomingTraceCannotInjectLogs() {
        try(RequestTrace trace=new RequestTrace("bad\ncredential",null)) {
            assertTrue(RequestTrace.valid(RequestTrace.current()));assertFalse(RequestTrace.current().contains("credential"));
        }
    }
    @Test void httpResponseAndRpcIdentityShareCorrelationAndDoNotLeakAfterRequest() throws Exception {
        MockHttpServletRequest request=new MockHttpServletRequest("GET","/api/article/list");request.addHeader("X-Request-Id","gateway-12345678");
        MockHttpServletResponse response=new MockHttpServletResponse();
        new RequestTraceFilter().doFilter(request,response,(req,res) -> {
            assertEquals("gateway-12345678",new AgentServiceAuth("a".repeat(32)).identity(7L).getTraceId());
        });
        assertEquals("gateway-12345678",response.getHeader("X-Request-Id"));assertNull(MDC.get("trace_id"));
    }
}
