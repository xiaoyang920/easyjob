package com.easyjob.interceptor;

import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.UserContext;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * JWT拦截器
 * 拦截所有需要登录的请求，验证JWT token
 * 并将用户信息存入ThreadLocal
 */
@Component
public class JwtInterceptor implements HandlerInterceptor {

    @Autowired
    private JwtUtil jwtUtil;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        String requestURI = request.getRequestURI();
        System.out.println("拦截器被触发，请求路径: " + requestURI);

        // 优先从 Authorization Header 取 token
        String authorization = request.getHeader("Authorization");
        String token = null;

        if (authorization != null && !authorization.isEmpty()) {
            token = jwtUtil.getTokenFromAuthorization(authorization);
        }

        // SSE/EventSource 不支持自定义 Header，允许从 query 参数取 token
        if ((token == null || token.isEmpty())) {
            String tokenParam = request.getParameter("token");
            if (tokenParam != null && !tokenParam.isEmpty()) {
                token = tokenParam;
            }
        }

        if (token == null || token.isEmpty()) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"code\":401,\"message\":\"未登录，请先登录\"}");
            return false;
        }

        try {
            // 提取用户信息并存入 ThreadLocal
            Long userId = jwtUtil.getUserIdFromToken(token);
            if (userId == null) throw new io.jsonwebtoken.JwtException("Missing principal");
            UserContext.setUserId(userId);

            System.out.println("用户验证成功 - userId: " + userId + " [已存入ThreadLocal]");
            return true;

        } catch (io.jsonwebtoken.JwtException | IllegalArgumentException e) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"code\":401,\"message\":\"登录已过期，请重新登录\"}");
            return false;
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"code\":503,\"message\":\"登录验证暂不可用，请稍后重试\"}");
            return false;
        }
    }

    /**
     * 请求完成后清理ThreadLocal，防止内存泄漏
     */
    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                                Object handler, Exception ex) throws Exception {
        UserContext.clear();
        System.out.println("请求结束，已清理ThreadLocal");
    }
}
