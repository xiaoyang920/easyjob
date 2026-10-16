package com.easyjob.config;
import com.alibaba.fastjson2.JSON;
import jakarta.annotation.*;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.connection.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;

/** Best-effort transport; messages and unread counts remain durable database facts. */
@Component @Slf4j
public class ChatRealtimeRelay implements MessageListener {
    private final StringRedisTemplate redis;private final String node=UUID.randomUUID().toString(),topic;
    public ChatRealtimeRelay(StringRedisTemplate redis,@Value("${easyjob.chat.topic:easyjob:chat:events:v1}")String topic){this.redis=redis;this.topic=topic;}
    @Bean public RedisMessageListenerContainer chatRedisListeners(RedisConnectionFactory factory){var c=new RedisMessageListenerContainer();c.setConnectionFactory(factory);c.addMessageListener(this,new ChannelTopic(topic));return c;}
    @PostConstruct public void install(){ChatWebSocketHandler.relay=(uid,data)->publish("message",uid,data);ChatWebSocketHandler.presence=this::isOnline;ChatWebSocketHandler.onlineUsers=this::online;ChatWebSocketHandler.presenceChanged=this::presence;ChatWebSocketHandler.revokeRelay=(uid,sid)->publish("revoke",uid,sid);}
    private String key(long uid){return topic+":presence:"+uid;}
    private String users(){return topic+":online";}
    private void touch(long uid){double until=System.currentTimeMillis()+60000;redis.opsForZSet().add(key(uid),node,until);redis.expire(key(uid),Duration.ofSeconds(90));redis.opsForZSet().add(users(),Long.toString(uid),until);}
    private boolean isOnline(long uid){try{Long n=redis.opsForZSet().count(key(uid),System.currentTimeMillis(),Double.POSITIVE_INFINITY);return n!=null && n>0;}catch(RuntimeException e){return false;}}
    private Set<Long> online(){try{var ids=redis.opsForZSet().rangeByScore(users(),System.currentTimeMillis(),Double.POSITIVE_INFINITY);var result=new HashSet<Long>();if(ids!=null)for(String id:ids)try{result.add(Long.parseLong(id));}catch(NumberFormatException ignored){}return result;}catch(RuntimeException e){return Set.of();}}
    private void presence(Long uid,boolean connected){try{if(connected){touch(uid);ChatWebSocketHandler.presenceLocal(uid,true);publish("online",uid,"");}else{redis.opsForZSet().remove(key(uid),node);if(!isOnline(uid)){redis.opsForZSet().remove(users(),uid.toString());ChatWebSocketHandler.presenceLocal(uid,false);publish("offline",uid,"");}}}catch(RuntimeException e){ChatWebSocketHandler.presenceLocal(uid,connected);log.warn("Presence synchronization unavailable");}}
    @Scheduled(fixedDelay=20000) public void heartbeat(){try{ChatWebSocketHandler.localUsers().forEach(this::touch);redis.opsForZSet().removeRangeByScore(users(),0,System.currentTimeMillis());}catch(RuntimeException e){log.warn("Chat presence heartbeat unavailable");}}
    private void publish(String kind,Long uid,String data){try{redis.convertAndSend(topic,JSON.toJSONString(Map.of("node",node,"kind",kind,"uid",uid.toString(),"data",data)));}catch(RuntimeException e){log.warn("Cross-node chat unavailable; persisted history remains readable");}}
    @Override public void onMessage(Message message,byte[] pattern){try{var value=JSON.parseObject(new String(message.getBody(),StandardCharsets.UTF_8));if(node.equals(value.getString("node")))return;Long uid=Long.valueOf(value.getString("uid"));String kind=value.getString("kind"),data=value.getString("data");switch(kind){case "message"->ChatWebSocketHandler.deliverLocal(uid,data);case "online"->ChatWebSocketHandler.presenceLocal(uid,true);case "offline"->{if(!isOnline(uid))ChatWebSocketHandler.presenceLocal(uid,false);}case "revoke"->ChatWebSocketHandler.disconnectLocal(uid,data==null || data.isEmpty()?null:data);default->{}}}catch(RuntimeException invalid){log.warn("Ignored invalid chat relay frame");}}
    @PreDestroy public void close(){ChatWebSocketHandler.localUsers().forEach(uid->{try{redis.opsForZSet().remove(key(uid),node);}catch(RuntimeException ignored){}});ChatWebSocketHandler.relay=null;ChatWebSocketHandler.presence=null;ChatWebSocketHandler.onlineUsers=null;ChatWebSocketHandler.presenceChanged=null;ChatWebSocketHandler.revokeRelay=null;}
}
