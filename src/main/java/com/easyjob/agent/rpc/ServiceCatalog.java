package com.easyjob.agent.rpc;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import jakarta.annotation.PreDestroy;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

/** Consul catalog adapter for native gRPC peers. Failed discovery expires, never falls back to a write retry. */
@Component
public class ServiceCatalog {
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
    private final ObjectMapper json;
    private final boolean enabled;
    private final String base, token, address, instance;
    private final int httpPort,rpcPort;
    private volatile boolean ready;
    private record Snapshot(List<String> peers, long refreshed) {}
    private volatile Snapshot snapshot = new Snapshot(List.of(), 0);
    private final ScheduledExecutorService refreshers = Executors.newScheduledThreadPool(2, runnable -> {
        var thread = new Thread(runnable, "consul-catalog"); thread.setDaemon(true); return thread;
    });
    public ServiceCatalog(ObjectMapper json,
            @Value("${SERVICE_DISCOVERY_ENABLED:false}") boolean enabled,
            @Value("${CONSUL_URL:http://127.0.0.1:8500}") String base,
            @Value("${CONSUL_TOKEN:}") String token,
            @Value("${SERVICE_ADVERTISE_HOST:127.0.0.1}") String address,
            @Value("${server.port:8080}") int httpPort,
            @Value("${agent.rpc.port:${BLOG_RPC_PORT:20881}}") int rpcPort,
            @Value("${BLOG_INSTANCE_ID:}") String instance) {
        this.json=json;this.enabled=enabled;this.base=base.replaceAll("/$","");this.token=token;
        this.address=address;this.httpPort=httpPort;this.rpcPort=rpcPort;
        this.instance=instance.isBlank()?"easyjob-blog-"+address.replace(':','_')+"-"+httpPort:instance;
    }
    public boolean enabled() { return enabled; }
    private String request(String method,String path,java.lang.Object body) throws Exception {
        var builder=HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(2));
        if (!token.isBlank()) builder.header("X-Consul-Token",token);
        builder.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body)));
        var response=http.send(builder.build(),HttpResponse.BodyHandlers.ofString());
        if(response.statusCode()/100!=2) throw new IllegalStateException("Service catalog unavailable");
        return response.body();
    }
    @EventListener(ApplicationReadyEvent.class) public void ready() {
        if (!enabled || ready) return;
        ready=true;
        // Initial discovery is startup work; user requests never perform registry I/O.
        refresh(); heartbeat();
        refreshers.scheduleWithFixedDelay(this::refresh, 5, 5, TimeUnit.SECONDS);
        refreshers.scheduleWithFixedDelay(this::heartbeat, 10, 10, TimeUnit.SECONDS);
    }
    public void heartbeat() {
        if (!enabled || !ready) return;
        try {
            request("PUT","/v1/agent/service/register",Map.of("ID",instance,"Name","easyjob-blog","Address",address,
                "Port",httpPort,"Meta",Map.of("rpc_port",Integer.toString(rpcPort)),
                "Check",Map.of("TTL","30s","DeregisterCriticalServiceAfter","5m")));
            request("PUT","/v1/agent/check/pass/service:"+instance,null);
        } catch (Exception ignored) { /* TTL withdraws an unreachable instance; never log credentials. */ }
    }
    public void refresh() {
        if (!enabled || !ready) return;
        try {
                var next=new ArrayList<String>();
                JsonNode items=json.readTree(request("GET","/v1/health/service/easyjob-agent?passing=true",null));
                for(var item:items) {
                    var s=item.path("Service");String host=s.path("Address").asText();int port=s.path("Meta").path("rpc_port").asInt();
                    if(!host.matches("[a-zA-Z0-9.:-]+") || port<1 || port>65535) continue;
                    next.add((host.contains(":")?"["+host+"]":host)+":"+port);
                }
                if (ready) snapshot=new Snapshot(next.stream().sorted().distinct().toList(), now());
        } catch(Exception ignored) { /* Readers enforce expiry even if refresh is still blocked. */ }
    }
    public List<String> healthyTargets() {
        var current=snapshot;
        return ready && now()-current.refreshed() <= Duration.ofSeconds(30).toNanos()
            ? current.peers() : List.of();
    }
    public String agentTarget(long userId) {
        return healthyTargets().stream().max(Comparator.comparingLong(p -> rendezvous(userId,p)))
            .orElseThrow(() -> new IllegalStateException("No healthy Agent instance"));
    }
    protected long now() { return System.nanoTime(); }
    static long rendezvous(long uid,String endpoint) {
        try {
            byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest((uid+":"+endpoint).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return java.nio.ByteBuffer.wrap(hash).getLong() & Long.MAX_VALUE;
        } catch(Exception e) { throw new IllegalStateException(e); }
    }
    @PreDestroy public void close() {
        ready=false;
        refreshers.shutdownNow();
        snapshot=new Snapshot(List.of(),0);
        if(enabled) try { request("PUT","/v1/agent/service/deregister/"+instance,null); } catch(Exception ignored) {}
    }
}
