package com.easyjob.config;

import com.easyjob.utils.JwtUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import java.util.Map;

@Component
@Slf4j
public class ChatHandshakeInterceptor implements HandshakeInterceptor {
    @Autowired
    private JwtUtil jwtUtil;
    /**
     * 握手前，验证token，把userID存入attributes
     * @param request
     * @param response
     * @param wsHandler
     * @param attributes
     * @return
     * @throws Exception
     */
    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) throws Exception {
        if(request instanceof ServletServerHttpRequest){
            ServletServerHttpRequest serverHttpRequest = (ServletServerHttpRequest) request;
            String token = serverHttpRequest.getServletRequest().getParameter("token");
            if(token != null){
                try{
                    Long userId = jwtUtil.getUserIdFromToken(token);
                    attributes.put("userId", userId);
                    String sid=jwtUtil.parseToken(token).get("sid",String.class);
                    if(sid!=null)attributes.put("authSessionId",sid);
                    return true;//允许连接
                } catch (Exception e) {
                    log.warn("用户token解析失败（忽略）: {}", e.getMessage());
                }
            }
        }
        return false;//拒绝连接
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response, WebSocketHandler wsHandler, Exception exception) {
        // do nothing
    }
}
