package com.easyjob.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
    @Autowired
    private ChatWebSocketHandler chatWebSocketHandler;

    @Autowired
    private ArticleWebSocketHandler articleWebSocketHandler;

    @Autowired
    private ArticleHandshakeInterceptor articleHandshakeInterceptor;
    @Autowired
    private ChatHandshakeInterceptor handshakeInterceptor;

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        // 聊天Socket
        registry.addHandler(chatWebSocketHandler, "/ws/chat")
                .addInterceptors(handshakeInterceptor)
                .setAllowedOrigins(
                        "http://localhost:3000",           // 前端开发环境（Vite默认端口）
                        "http://85.137.247.222",           // 生产环境IP
                        "http://xiaoyanga.xyz",            // 你的域名（HTTP）
                        "https://xiaoyanga.xyz"            // 你的域名（HTTPS）
                );
        // 文章Socket
        registry.addHandler(articleWebSocketHandler, "/ws/article")
                .addInterceptors(articleHandshakeInterceptor)
                .setAllowedOrigins(
                        "http://localhost:3000",           // 前端开发环境（Vite默认端口）
                        "http://85.137.247.222",           // 生产环境IP
                        "http://xiaoyanga.xyz",            // 你的域名（HTTP）
                        "https://xiaoyanga.xyz"            // 你的域名（HTTPS）
                );
    }
}
