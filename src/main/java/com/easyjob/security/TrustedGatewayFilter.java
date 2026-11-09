package com.easyjob.security;

import com.easyjob.utils.UserContext;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import java.io.IOException;
import java.util.Enumeration;

/** Verifies gateway assertions for every external HTTP entry, including optional-login reads. */
@Component @Order(-100) @ConditionalOnProperty(name="easyjob.auth.enabled",havingValue="true")
public class TrustedGatewayFilter extends OncePerRequestFilter {
    public static final String ATTRIBUTE=TrustedGatewayFilter.class.getName()+".identity";
    private final JwtDecoder decoder;
    public TrustedGatewayFilter(@Value("${easyjob.auth.gateway-public-key-file}")String file){decoder=IdentityTokens.decoder(IdentityTokens.key(file),"easyjob-gateway","easyjob-blog",IdentityTokens.INTERNAL);}
    @Override protected boolean shouldNotFilter(HttpServletRequest request){String p=request.getRequestURI();return p.equals("/actuator/health")||p.equals("/error")||p.equals("/internal/agent/ready")||p.equals("/internal/agent/drafts")||p.startsWith("/internal/agent/drafts/");}
    @Override protected boolean shouldNotFilterAsyncDispatch(){return false;}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
        IdentityTokens.Principal principal=(IdentityTokens.Principal)request.getAttribute(ATTRIBUTE);
        if(principal==null)try{
            Enumeration<String> headers=request.getHeaders(IdentityTokens.HEADER);if(headers==null||!headers.hasMoreElements())throw new IllegalArgumentException();String token=headers.nextElement();if(headers.hasMoreElements())throw new IllegalArgumentException();
            principal=IdentityTokens.forRequest(decoder,token,request.getMethod(),request.getRequestURI());
            if(principal.anonymous()&&RoutePolicy.access(request.getMethod(),request.getRequestURI())==RoutePolicy.Access.REQUIRED)throw new IllegalArgumentException();
            if(RoutePolicy.authRoute(request.getRequestURI()))throw new IllegalArgumentException(); // These routes now belong only to Auth.
            request.setAttribute(ATTRIBUTE,principal);
        }catch(RuntimeException invalid){response.setStatus(401);response.setContentType("application/json;charset=UTF-8");response.getWriter().write("{\"code\":401,\"message\":\"请求身份无效，请通过统一入口访问\"}");return;}
        try{RequestIdentity.set(principal);UserContext.setUserId(principal.anonymous()?null:Long.valueOf(principal.userId()));chain.doFilter(request,response);}
        finally{RequestIdentity.clear();UserContext.clear();}
    }
}
