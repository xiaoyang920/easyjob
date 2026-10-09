package com.easyjob.config;



import com.alibaba.fastjson2.JSON;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.UserInfo;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArraySet;

@Component
@Slf4j
public class ArticleWebSocketHandler extends TextWebSocketHandler {
    @Autowired
    private RedisComponent redisComponent;
    
    private static final Map<String, Set<WebSocketSession>> ARTICLE_SESSIONS = new ConcurrentHashMap<>();
    private static final Map<WebSocketSession, UserInfo> SESSIONS = new ConcurrentHashMap<>();

    public void disconnectUser(Long id) {
        SESSIONS.forEach((session,user)->{
            if(id.toString().equals(user.getUserId())) try {session.close(CloseStatus.POLICY_VIOLATION);}
            catch(IOException e){log.warn("Cannot close revoked article session for {}",id,e);}
        });
    }

    /**
     * 连接建立成功
     * @param session
     * @throws Exception
     */
    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        // 获取用户ID
        UserInfo userInfo = getUserInfo(session);
        if (userInfo!= null) {
            SESSIONS.put(session,userInfo);
            log.info("用户" + userInfo.getUserId() + " 已连接文章，当前在线人数: " + SESSIONS.size());
        }
    }
    /**
     * 接收到消息
     * @param session
     * @param message
     * @throws Exception
     */
    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        String payload = message.getPayload();
        Map<String, Object> msg = JSON.parseObject(payload, Map.class);
        String type = (String) msg.get("type");

        if ("ping".equals(type)) {
            // 心跳响应，同时刷新用户Redis缓存过期时间
            UserInfo userInfo = getUserInfo(session);
            if (userInfo != null) {
                redisComponent.refreshUserSpaceExpire(Long.parseLong(userInfo.getUserId()));
            }
            sendMessageSafe(session, new TextMessage("{\"type\":\"pong\"}"));
        } else if ("join_article".equals(type)) {
            handleJoinArticle(session, msg);
        } else if ("leave_article".equals(type)) {
            handleLeaveArticle(session, msg);
        } else if ("article_chat_message".equals(type)) {
            handleChatMessage(session, msg);
        }
    }
    /**
     * 处理聊天信息
     * @param session
     * @param msg
     */
    private void handleChatMessage(WebSocketSession session, Map<String, Object> msg) {
        String articleId = msg.get("articleId").toString();
        String content = msg.get("content").toString();
        UserInfo userInfo = getUserInfo(session);
        if (userInfo == null || content.trim().isEmpty()) {
            return;
        }
        //构建消息
        Map<String, Object> messageData = new HashMap<>();
        messageData.put("type", "article_chat_message");
        messageData.put("articleId", articleId);
        messageData.put("userId", userInfo.getUserId());
        messageData.put("nickName", userInfo.getNickName());
        messageData.put("avatar", userInfo.getAvatar());
        messageData.put("content", content);
        messageData.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME));
        //广播消息
        broadcastToArticle(articleId, JSON.toJSONString(messageData));
    }
    /**
     * 处理异常
     * @param session
     * @param exception
     * @throws Exception
     */
    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) throws Exception {
        cleanupSession(session);
    }
    /**
     * 连接关闭
     * @param session
     * @param status
     * @throws Exception
     */
    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) throws Exception {
        cleanupSession(session);
    }


    /**
     * 离开文章
     * @param session
     * @param msg
     */
    private void handleLeaveArticle(WebSocketSession session, Map<String, Object> msg) {
        String articleId = msg.get("articleId").toString();
        removeSessionFromArticle(session, articleId);
    }


    private void handleJoinArticle(WebSocketSession session, Map<String, Object> msg) {
        String articleId = msg.get("articleId").toString();
        UserInfo userInfo = getUserInfo(session);
        if (userInfo == null) {
            return;
        }
        //更新用户所在文章
        userInfo.setCurrentArticleId(articleId);
        //添加用户到文章会话
        ARTICLE_SESSIONS.computeIfAbsent(articleId, k -> new CopyOnWriteArraySet<>()).add( session);
        //广播在线用户表更新
        broadcastUsersUpdate(articleId);
    }
    /**
     * 清理session
     * @param session
     */
    private void cleanupSession(WebSocketSession session) {
        //移除用户会话
        UserInfo userInfo = SESSIONS.remove(session);
        if(userInfo!= null&&userInfo.getCurrentArticleId()!= null){
            String articleId = userInfo.getCurrentArticleId();
            if(!articleId.isEmpty()){
                removeSessionFromArticle(session, articleId);
            }
        }
    }
    /**
     * 广播文章消息
     * @param articleId
     * @param jsonString
     */
    private void broadcastToArticle(String articleId, String jsonString) {
        Set<WebSocketSession> sessions = ARTICLE_SESSIONS.get(articleId);
        if(sessions== null){
            return;
        }
        TextMessage textMessage = new TextMessage(jsonString);
        sessions.forEach(s -> sendMessageSafe(s, textMessage));
    }
    /**
     * 移除用户会话
     * @param session
     * @param articleId
     */
    private void removeSessionFromArticle(WebSocketSession session, String articleId) {
        Set<WebSocketSession> sessions = ARTICLE_SESSIONS.get(articleId);
        if (sessions == null) {
            return;
        }
        sessions.remove(session);
        if (sessions.isEmpty()) {
            ARTICLE_SESSIONS.remove(articleId);
        } else {
            broadcastUsersUpdate(articleId);
        }
    }
    /**
     * 广播更新文章在线用户表
     * @param articleId
     */
    private void broadcastUsersUpdate(String articleId) {
        //获取文章会话
        Set<WebSocketSession> sessions = ARTICLE_SESSIONS.get(articleId);
        if(sessions == null|| sessions.isEmpty()){
            return;
        }
        //更新构建用户表（按userId去重，同一用户多个标签页只显示一次）
        Map<String, Map<String, String>> userMap = new HashMap<>();
        for (WebSocketSession session : sessions) {
            UserInfo userInfo = SESSIONS.get(session);
            if (userInfo != null && !userMap.containsKey(userInfo.getUserId())) {
                Map<String, String> user = new HashMap<>();
                user.put("userId", userInfo.getUserId());
                user.put("avatar", userInfo.getAvatar());
                user.put("nickName", userInfo.getNickName());
                userMap.put(userInfo.getUserId(), user);
            }
        }
        List<Map<String, String>> users = new ArrayList<>(userMap.values());
        Map<String, Object> messageData = new HashMap<>();
        messageData.put("type", "article_users_update");
        messageData.put("articleId", articleId);
        messageData.put("users", users);
        //广播消息
        broadcastArticle(articleId, JSON.toJSONString(messageData));
    }

    /**
     * 广播文章消息
     * @param articleId
     * @param message
     */
    private void broadcastArticle(String articleId,String message){
        Set<WebSocketSession> sessions = ARTICLE_SESSIONS.get(articleId);
        if(sessions == null|| sessions.isEmpty()){
            return;
        }
        TextMessage textMessage = new TextMessage(message);
        sessions.forEach(session -> {
            sendMessageSafe(session, textMessage);
        });

    }
    /**
     * 线程安全的消息发送（解决并发写入问题）
     * @param session
     * @param message
     */
    private void sendMessageSafe(WebSocketSession session, TextMessage message){
        if(session!=null&& session.isOpen()){
            synchronized (session){
                try {
                    session.sendMessage(message);
                } catch (IOException e) {
                    log.error("发送消息失败: " + e.getMessage(), e);
                }
            }
        }
    }

    private UserInfo getUserInfo(WebSocketSession session) {
        Object o = session.getAttributes().get("userInfo");
        return o == null ? null : (UserInfo) o;
    }

}
