package com.easyjob.gateway;

import com.easyjob.security.*;
import com.nimbusds.jose.jwk.*;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.*;
import java.nio.file.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.security.IdentityTokens.Principal;
import com.nimbusds.jose.jwk.RSAKey;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

class DirectAgentTests {
    @TempDir Path temp;

    @Test void gatewayIssuesAgentAudienceAndStripsExternalIdentity() throws Exception {
        RSAKey authKey=new RSAKeyGenerator(2048).keyID("auth-test").generate();
        RSAKey gatewayKey=new RSAKeyGenerator(2048).keyID("gateway-test").generate();
        Path file=temp.resolve("gateway.json");Files.writeString(file,gatewayKey.toJSONString());
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        AtomicInteger checks=new java.util.concurrent.atomic.AtomicInteger();
        server.createContext("/jwks",exchange->{byte[] bytes=new JWKSet(authKey.toPublicJWK()).toString().getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();});
        server.createContext("/internal/auth/session/check",exchange->{checks.incrementAndGet();byte[] bytes=("{\"code\":200,\"data\":{\"userId\":\"7\",\"sid\":\""+"a".repeat(64)+"\",\"version\":2,\"roles\":[\"1\"]}}").getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();});
        server.start();
        try {
            ReactiveStringRedisTemplate redis=mock(ReactiveStringRedisTemplate.class);when(redis.execute(any(),anyList(),anyList())).thenReturn(Flux.just(1L));
            String base="http://127.0.0.1:"+server.getAddress().getPort();
            UnifiedIdentityFilter filter=new UnifiedIdentityFilter(redis,base,base+"/jwks","easyjob-auth",file.toString(),"s".repeat(48),300,20,12);
            Principal p=new IdentityTokens.Principal("7","a".repeat(64),2,List.of());
            String access=IdentityTokens.issue(IdentityTokens.encoder(authKey),authKey.getKeyID(),"easyjob-auth","easyjob-api",IdentityTokens.ACCESS,p,60,null,null,null);
            NimbusJwtDecoder decoder=IdentityTokens.decoder(gatewayKey.toPublicJWK(),"easyjob-gateway","easyjob-agent",IdentityTokens.INTERNAL);
            MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/agent/chat/stream?token="+access)
                .header("X-Agent-Key","forged").header("X-Agent-User","8").header("X-Easyjob-Identity","forged"));
            filter.filter(exchange,next->{
                ServerHttpRequest request=next.getRequest();
                assertNull(request.getHeaders().getFirst("Authorization"));
                assertNull(request.getHeaders().getFirst("X-Agent-Key"));
                assertNull(request.getHeaders().getFirst("X-Agent-User"));
                assertFalse(request.getQueryParams().containsKey("token"));
                Principal principal=IdentityTokens.forRequest(decoder,request.getHeaders().getFirst(IdentityTokens.HEADER),"POST","/api/agent/chat/stream");
                assertEquals("7",principal.userId());assertEquals(List.of("1"),principal.roles());
                return Mono.empty();
            }).block(Duration.ofSeconds(10));
            assertEquals(1,checks.get());
        } finally {server.stop(0);}
    }

    @Test void agentRoutePrecedesCatchAllAndKeepsPublicPath() {
        Map document=new org.yaml.snakeyaml.Yaml().loadAs(getClass().getResourceAsStream("/application.yml"),Map.class);
        Map<?, ?> spring=(Map<?,?>)document.get("spring");Map<?, ?> cloud=(Map<?,?>)spring.get("cloud");Map<?, ?> gateway=(Map<?,?>)cloud.get("gateway");
        List<Map<String, Object>> routes=(List<Map<String,Object>>)gateway.get("routes");
        int agent=-1,blog=-1;
        for(int i=0;i<routes.size();i++) {
            Map<String, Object> route=routes.get(i);
            if("agent-api".equals(route.get("id"))){agent=i;assertEquals("lb://easyjob-agent",route.get("uri"));assertEquals(List.of("Path=/api/agent/**"),route.get("predicates"));assertNull(route.get("filters"));}
            if("blog-api".equals(route.get("id")))blog=i;
        }
        assertTrue(agent>=0&&blog>agent);
        assertEquals("easyjob-agent",RoutePolicy.audience("/api/agent/conversations"));
        assertEquals("easyjob-blog",RoutePolicy.audience("/api/admin/agent-feedback"));
        assertEquals("easyjob-auth",RoutePolicy.audience("/api/account/sessions"));
    }
}
