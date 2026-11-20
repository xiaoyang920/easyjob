package com.easyjob.config;
import com.alibaba.fastjson2.JSON;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.*;
import com.easyjob.security.IdentityTokens.Principal;
import java.util.HashSet;
import java.util.Set;
import java.util.function.BiConsumer;
import org.springframework.web.socket.WebSocketSession;

@Component @Slf4j
public class ChatWebSocketHandler extends TextWebSocketHandler {
    private static final Map<Long,Set<WebSocketSession>> SESSIONS=new ConcurrentHashMap<>();
    static volatile BiConsumer<Long,String> relay,revokeRelay;
    static volatile Predicate<Long> presence;
    static volatile Supplier<Set<Long>> onlineUsers;
    public static volatile Function<Long,Set<Long>> presenceAudience;
    static volatile BiConsumer<Long,Boolean> presenceChanged;
    private static Long user(WebSocketSession session){Object id=session.getAttributes().get("userId");return id instanceof Number n?n.longValue():null;}
    @Override public void afterConnectionEstablished(WebSocketSession session){
        Principal identity=(com.easyjob.security.IdentityTokens.Principal)session.getAttributes().get("authPrincipal");
        session.getAttributes().put("authRegistration",com.easyjob.security.ConnectionSessions.register(identity,()->{try{session.close(CloseStatus.POLICY_VIOLATION);}catch(IOException ignored){}}));
        Long uid=user(session);if(uid==null)return;boolean first;
        synchronized(SESSIONS){Set<WebSocketSession> sessions=SESSIONS.computeIfAbsent(uid,k->ConcurrentHashMap.newKeySet());first=sessions.isEmpty();sessions.add(session);}
        if(first)changePresence(uid,true);
        sendSafe(session,JSON.toJSONString(Map.of("type","online_users","userIds",visibleOnline(uid))));
    }
    @Override protected void handleTextMessage(WebSocketSession session,TextMessage message){try{if("ping".equals(JSON.parseObject(message.getPayload()).getString("type")))sendSafe(session,"{\"type\":\"pong\"}");}catch(RuntimeException invalid){log.debug("Ignored invalid socket frame");}}
    @Override public void afterConnectionClosed(WebSocketSession session,CloseStatus status){
        try{Object r=session.getAttributes().get("authRegistration");if(r instanceof AutoCloseable registration)registration.close();}catch(Exception ignored){}
        Long uid=user(session);if(uid==null)return;boolean last=false;
        synchronized(SESSIONS){Set<WebSocketSession> sessions=SESSIONS.get(uid);if(sessions!=null){sessions.remove(session);if(sessions.isEmpty()){SESSIONS.remove(uid);last=true;}}}
        if(last)changePresence(uid,false);
    }
    @Override public void handleTransportError(WebSocketSession session,Throwable error)throws IOException{session.close();}
    private static void sendSafe(WebSocketSession session,String message){if(session==null || !session.isOpen())return;synchronized(session){try{session.sendMessage(new TextMessage(message));}catch(IOException e){log.warn("Chat delivery failed; reload persisted messages");}}}
    static void deliverLocal(Long uid,String data){Set<WebSocketSession> sessions=SESSIONS.get(uid);if(sessions!=null)sessions.forEach(s->sendSafe(s,data));}
    public static void sendToUser(Long uid,String data){if(uid==null)return;deliverLocal(uid,data);BiConsumer<Long, String> publisher=relay;if(publisher!=null)publisher.accept(uid,data);}
    public static void sendToUser(Long uid,Map<String,Object> data){sendToUser(uid,JSON.toJSONString(data));}
    public static boolean isOnline(Long uid){if(uid==null)return false;Set<WebSocketSession> sessions=SESSIONS.get(uid);return sessions!=null && sessions.stream().anyMatch(WebSocketSession::isOpen) || presence!=null && presence.test(uid);}
    static Set<Long> localUsers(){return Set.copyOf(SESSIONS.keySet());}
    public static Set<Long> getOnlineUserIds(){HashSet<Long> ids=new HashSet<>(localUsers());if(onlineUsers!=null)ids.addAll(onlineUsers.get());return ids;}
    private static void changePresence(Long uid,boolean online){if(presenceChanged!=null)presenceChanged.accept(uid,online);else presenceLocal(uid,online);}
    private static Set<Long> audience(Long uid){try{return presenceAudience==null?Set.of():presenceAudience.apply(uid);}catch(RuntimeException unavailable){return Set.of();}}
    private static List<String> visibleOnline(Long uid){Set<Long> allowed=audience(uid);return getOnlineUserIds().stream().filter(allowed::contains).map(Object::toString).toList();}
    public static void refreshPresence(Long uid){sendToUser(uid,Map.of("type","online_users","userIds",visibleOnline(uid)));}
    static void presenceLocal(Long uid,boolean online){String data=JSON.toJSONString(Map.of("type",online?"online":"offline","userId",uid.toString()));SESSIONS.forEach((id,sessions)->{if(!id.equals(uid)&&audience(id).contains(uid))sessions.forEach(s->sendSafe(s,data));});}
    static void disconnectLocal(Long uid,String sid){Set<WebSocketSession> sessions=SESSIONS.get(uid);if(sessions!=null)for(WebSocketSession session:List.copyOf(sessions))if(sid==null || sid.equals(session.getAttributes().get("authSessionId")))try{session.close(CloseStatus.POLICY_VIOLATION);}catch(IOException e){log.warn("Cannot close revoked socket");}}
    public void disconnectUser(Long uid){disconnectLocal(uid,null);if(revokeRelay!=null)revokeRelay.accept(uid,"");}
    public static void disconnectSession(Long uid,String sid){disconnectLocal(uid,sid);if(revokeRelay!=null)revokeRelay.accept(uid,sid);}
}
