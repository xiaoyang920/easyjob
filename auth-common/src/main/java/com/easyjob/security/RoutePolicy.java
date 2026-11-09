package com.easyjob.security;
import java.util.Set;
public final class RoutePolicy {
    public enum Access { PUBLIC, OPTIONAL, REQUIRED, INTERNAL }
    private RoutePolicy(){}
    public static boolean agentRoute(String path){return path.equals("/api/agent")||path.startsWith("/api/agent/");}
    public static String audience(String path){return authRoute(path)?"easyjob-auth":agentRoute(path)?"easyjob-agent":"easyjob-blog";}
    public static boolean authRoute(String path){return path.startsWith("/api/auth/")||path.startsWith("/api/account/")||path.matches("/api/admin/accounts/[0-9]+/security");}
    public static Access access(String method,String path){
        if(path.startsWith("/internal")||path.startsWith("/actuator")||path.startsWith("/error"))return Access.INTERNAL;
        if("GET".equals(method)&&path.equals("/api/auth/jwks"))return Access.PUBLIC;
        if("POST".equals(method)&&Set.of("/api/auth/login","/api/auth/register","/api/auth/login-by-email","/api/auth/send-code","/api/auth/refresh","/api/auth/logout","/api/auth/password/code","/api/auth/password/reset").contains(path))return Access.PUBLIC;
        if("GET".equals(method)&&(Set.of("/api/article/list","/api/article/recommend","/api/category/list","/api/comment/list","/api/comment/replies","/api/comment/quotes","/api/comment/quote-markers","/api/search").contains(path)||path.startsWith("/api/article/detail/")||path.matches("/api/article/user/[0-9]+")||path.startsWith("/api/user/space/")||path.startsWith("/api/search/")))return Access.OPTIONAL;
        if("POST".equals(method)&&path.matches("/api/article/[0-9]+/view"))return Access.OPTIONAL;
        if("GET".equals(method)&&(path.startsWith("/uploads/")||path.equals("/")))return Access.PUBLIC;
        return Access.REQUIRED;
    }
}
