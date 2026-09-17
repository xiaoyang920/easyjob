package com.easyjob.config;

import com.alibaba.fastjson2.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;


@Component
@Slf4j
public class ChatWebSocketHandler  extends TextWebSocketHandler {
    /**
     * 存储用户ID和WebSocketSession的映射关系
     */
    private static final Map<Long, WebSocketSession> SESSIONS = new ConcurrentHashMap<>();
    /**
     * 连接建立
     * @param session
     * @throws Exception
     */
    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        Long userId = getUserId(session);
        if(userId != null){
            SESSIONS.put(userId, session);
            log.info("用户 " + userId + " 已连接，当前在线人数: " + SESSIONS.size());

            //发送在线用户列表给该用户
            sendOnlineUserList(session);
            //广播该用户上线
            broadcastOnlineStatus(userId, true);
        }
    }
    /**
     * 接收到消息（主要处理心跳）
     * @param session
     * @param message
     * @throws Exception
     */
    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        String payload = message.getPayload();
        Map<String, Object> msg = JSON.parseObject(payload, Map.class);
        String type = (String) msg.get("type");
        if("ping".equals(type)){
            // 心跳响应
            sendMessageSafe(session, new TextMessage("{\"type\":\"pong\"}"));
        }
    }
    /**
     * 连接关闭
     * @param session
     * @param status
     * @throws Exception
     */
    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) throws Exception {
        Long userId = getUserId(session);
        if(userId != null){
            SESSIONS.remove(userId);
            // 广播该用户下线
            log.info("用户 " + userId + " 已断开，当前在线人数: " + SESSIONS.size());
            broadcastOnlineStatus(userId, false);
        }
    }
    /**
     * 错误处理
     * @param session
     * @param exception
     * @throws Exception
     */
    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) throws Exception {
        Long userId = getUserId(session);
        log.error("用户 " + userId + " 错误: " + exception.getMessage(), exception);
        if(session.isOpen()){
            session.close();
        }
    }
    /**
     * 线程安全的消息发送（解决并发写入问题）
     * @param session
     * @param message
     */
    private static void sendMessageSafe(WebSocketSession session, TextMessage message) {
        if (session != null && session.isOpen()) {
            synchronized (session) {
                try {
                    session.sendMessage(message);
                } catch (IOException e) {
                    log.error("发送消息失败: " + e.getMessage(), e);
                }
            }
        }
    }
    
    /**
     * 发送消息给指定用户
     * @param userId
     * @param message
     */
    public static void sendToUser(Long userId, String message){
        WebSocketSession session = SESSIONS.get(userId);
        sendMessageSafe(session, new TextMessage(message));
    }
    /**

     * 发送消息给指定用（Map自动转JSON）
     * @param userId
     * @param data
     */
    public static void sendToUser(Long userId,Map<String, Object> data){

        sendToUser(userId, JSON.toJSONString(data));
    }
    /**
     * 判断用户是否在线
     * @param userId
     * @return
     */
    public static boolean isOnline(Long userId) {
        WebSocketSession session = SESSIONS.get(userId);
        return session != null && session.isOpen();
    }
    /**
     * 获取所有在线用户ID
     * @return
     */
    public static Set<Long> getOnlineUserIds() {
        return SESSIONS.keySet();
    }
    /**
     * 获取用户ID
     * @param session
     * @return
     */
    private Long getUserId(WebSocketSession session) {
        Object userId = session.getAttributes().get("userId");
        return userId == null ? null : (Long) userId;
    }
    /**
     * 发送在线用户列表给该用户
     * @param session
     */
    private void sendOnlineUserList(WebSocketSession session) {
        Map<String, Object> msg = new HashMap<>();
        msg.put("type", "online_users");
        msg.put("userIds", SESSIONS.keySet().stream().map(Object::toString).toList());
        sendMessageSafe(session, new TextMessage(JSON.toJSONString(msg)));
    }
    /**
     * 广播用户上线或下线
     * @param userId
     * @param online
     */
    private void broadcastOnlineStatus(Long userId, boolean online) {
        Map<String, Object> msg = new HashMap<>();
        msg.put("type", online ? "online" : "offline");
        msg.put("userId", userId.toString());
        TextMessage textMessage = new TextMessage(JSON.toJSONString(msg));
        SESSIONS.forEach((uid, session) -> {
            if (!uid.equals(userId) && session.isOpen()) {
                sendMessageSafe(session, textMessage);
            }
        });
    }
}
