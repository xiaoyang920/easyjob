package com.easyjob.observability;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;

@Component
public class RequestTraceFilter extends OncePerRequestFilter {
    private static final org.slf4j.Logger log=LoggerFactory.getLogger(RequestTraceFilter.class);
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)
            throws ServletException,IOException {
        long started=System.nanoTime();
        try(var trace=new RequestTrace(request.getHeader("X-Request-Id"),null)) {
            response.setHeader("X-Request-Id",RequestTrace.current());
            try { chain.doFilter(request,response); }
            finally { log.info("http_dispatch trace={} method={} status={} duration_ms={} async={}",
                RequestTrace.current(),request.getMethod(),response.getStatus(),(System.nanoTime()-started)/1_000_000,request.isAsyncStarted()); }
        }
    }
}
