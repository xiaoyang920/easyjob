package com.easyjob.auth;

import com.easyjob.security.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.web.servlet.config.annotation.*;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.security.oauth2.jwt.*;
import jakarta.servlet.http.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import com.easyjob.security.IdentityTokens.Principal;

@Configuration
public class AuthConfiguration implements WebMvcConfigurer {
    final JwtDecoder gateway;final String serviceKey;final Sessions sessions;
    public AuthConfiguration(@Value("${auth.gateway-public-key-file}")String path,@Value("${auth.service-key}")String key,Sessions sessions){
        gateway=IdentityTokens.decoder(IdentityTokens.key(path),"easyjob-gateway","easyjob-auth",IdentityTokens.INTERNAL);
        if(key.getBytes(StandardCharsets.UTF_8).length<32)throw new IllegalStateException("Auth service credential missing");serviceKey=key;this.sessions=sessions;
    }
    @Override public void addInterceptors(InterceptorRegistry registry){registry.addInterceptor(new HandlerInterceptor(){
        @Override public boolean preHandle(HttpServletRequest request,HttpServletResponse response,Object handler){
            String path=request.getRequestURI();if(path.equals("/actuator/health")||path.equals("/error"))return true;
            if(!"GET".equals(request.getMethod())&&"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw new AuthFailure(403,"不允许跨站账号操作");
            if(path.startsWith("/internal/auth/")){
                String supplied=request.getHeader("X-Auth-Service-Key");
                if(supplied==null||!MessageDigest.isEqual(serviceKey.getBytes(StandardCharsets.UTF_8),supplied.getBytes(StandardCharsets.UTF_8)))throw new AuthFailure(401,"服务身份无效");return true;
            }
            if(RoutePolicy.access(request.getMethod(),path)==RoutePolicy.Access.PUBLIC)return true;
            try{
                Principal identity=IdentityTokens.forRequest(gateway,request.getHeader(IdentityTokens.HEADER),request.getMethod(),path);
                if(identity.anonymous())throw Sessions.expired();
                identity=sessions.check(identity.userId(),identity.sid(),identity.version());request.setAttribute("identity",identity);return true;
            }catch(org.springframework.security.oauth2.jwt.JwtException|IllegalArgumentException error){throw Sessions.expired();}
        }
    });}
    @Bean public org.springframework.boot.ApplicationRunner authSchemaCheck(AccountStore store){return args->store.schema();}
    @Bean public org.springframework.amqp.core.FanoutExchange authEvents(){return new org.springframework.amqp.core.FanoutExchange("easyjob.auth.revoked",true,false);}
    @Bean public org.springframework.amqp.support.converter.Jackson2JsonMessageConverter authMessageConverter(){return new org.springframework.amqp.support.converter.Jackson2JsonMessageConverter();}
}
