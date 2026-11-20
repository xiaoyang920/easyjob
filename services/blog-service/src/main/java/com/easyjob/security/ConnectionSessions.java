package com.easyjob.security;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Bean;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.listener.SimpleMessageListenerContainer;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.*;
import jakarta.annotation.PreDestroy;
import reactor.core.publisher.*;
import java.util.*;
import java.util.concurrent.*;
import com.easyjob.security.IdentityTokens.Principal;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import org.springframework.amqp.core.FanoutExchange;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import reactor.core.publisher.Sinks.Empty;
@Component @ConditionalOnProperty(name="easyjob.auth.enabled",havingValue="true")
public class ConnectionSessions {
    private record Entry(IdentityTokens.Principal identity,Runnable close){}
    private static final Map<String,Entry> CONNECTIONS=new ConcurrentHashMap<>();private static volatile ConnectionSessions active;
    private final AuthStateClient auth;private final ObjectMapper json;
    private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"auth-connection-check");t.setDaemon(true);return t;});
    public ConnectionSessions(AuthStateClient auth,ObjectMapper json){this.auth=auth;this.json=json;active=this;}
    public static AutoCloseable register(IdentityTokens.Principal p,Runnable close){if(p==null||p.anonymous()||active==null)return ()->{};String id=UUID.randomUUID().toString();CONNECTIONS.put(id,new Entry(p,close));return ()->CONNECTIONS.remove(id);}
    public static <T> Flux<T> guard(Flux<T> source,IdentityTokens.Principal p){if(p==null||active==null)return source;return Flux.defer(()->{Empty<Object> revoked=Sinks.empty();AutoCloseable registration=register(p,()->revoked.tryEmitEmpty());return source.takeUntilOther(revoked.asMono()).doFinally(signal->{try{registration.close();}catch(Exception ignored){}});});}
    private void receive(byte[] bytes){try{JsonNode value=json.readTree(bytes);String user=value.path("userId").asText(),sid=value.path("sid").asText();CONNECTIONS.values().stream().filter(e->user.equals(e.identity.userId())&&(sid.isEmpty()||sid.equals(e.identity.sid()))).toList().forEach(this::close);}catch(Exception invalid){org.slf4j.LoggerFactory.getLogger(getClass()).warn("Invalid auth revocation event");}}
    private void close(Entry entry){try{entry.close.run();}catch(RuntimeException ignored){}}
    @Bean public RedisMessageListenerContainer authRedisListeners(RedisConnectionFactory factory){RedisMessageListenerContainer c=new RedisMessageListenerContainer();c.setConnectionFactory(factory);c.addMessageListener((message,pattern)->receive(message.getBody()),new ChannelTopic("easyjob:auth:revoke"));return c;}
    @Bean public AnonymousQueue authRevocationQueue(){return new AnonymousQueue();}
    @Bean public Declarables authRevocationBindings(AnonymousQueue authRevocationQueue){FanoutExchange exchange=new FanoutExchange("easyjob.auth.revoked",true,false);return new Declarables(exchange,authRevocationQueue,BindingBuilder.bind(authRevocationQueue).to(exchange));}
    @Bean public SimpleMessageListenerContainer authRevocationListener(ConnectionFactory factory,AnonymousQueue authRevocationQueue){SimpleMessageListenerContainer c=new SimpleMessageListenerContainer(factory);c.setQueues(authRevocationQueue);c.setMessageListener((MessageListener)message->receive(message.getBody()));return c;}
    @EventListener(ApplicationReadyEvent.class)public void start(){worker.scheduleWithFixedDelay(this::check,30,30,TimeUnit.SECONDS);}
    void check(){List<Entry> entries=List.copyOf(CONNECTIONS.values());LinkedHashMap<String, Principal> unique=new LinkedHashMap<String,IdentityTokens.Principal>();entries.forEach(e->unique.put(e.identity.sid(),e.identity));ArrayList<Principal> values=new ArrayList<>(unique.values());for(int start=0;start<values.size();start+=50){List<Principal> batch=values.subList(start,Math.min(start+50,values.size()));Set<String> ids=new HashSet<>();batch.forEach(p->ids.add(p.sid()));Map<String,Boolean> validity;try{validity=auth.batch(batch);}catch(Exception unavailable){validity=Map.of();}for(Entry e:entries)if(ids.contains(e.identity.sid())&&!Boolean.TRUE.equals(validity.get(e.identity.sid())))close(e);}}
    @PreDestroy public void stop(){active=null;worker.shutdownNow();CONNECTIONS.values().forEach(this::close);CONNECTIONS.clear();}
}
