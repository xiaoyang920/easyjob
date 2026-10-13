package com.easyjob.gateway;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "spring.cloud.consul.enabled=false","spring.cloud.consul.discovery.enabled=false",
    "easyjob.jwt.secret-key="+EdgeFilterTests.SECRET})
class ForwardingTests {
    @org.junit.jupiter.api.AfterAll static void closeUpstream() { upstream.stop(0); }
    @MockitoBean ReactiveStringRedisTemplate redis;
    @LocalServerPort int port;
    static final AtomicInteger writes=new AtomicInteger();
    static final AtomicInteger disconnectedWrites=new AtomicInteger();
    static final HttpServer upstream;
    static {
        try {
            upstream=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
            upstream.createContext("/api/stream",e->{
                e.getResponseHeaders().set("Content-Type","text/event-stream");e.sendResponseHeaders(200,0);
                try(var out=e.getResponseBody()) {
                    out.write("data:first\n\n".getBytes());out.flush();
                    try {Thread.sleep(3000);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
                    out.write("data:last\n\n".getBytes());out.flush();
                } catch(java.io.IOException disconnected) { /* client deliberately cancels after first frame */ }
                e.close();
            });
            upstream.createContext("/api/write",e->{
                writes.incrementAndGet();byte[] body=e.getRequestBody().readAllBytes();
                e.getResponseHeaders().set("Content-Type","application/json");e.sendResponseHeaders(200,body.length);
                e.getResponseBody().write(body);e.close();
            });
            upstream.createContext("/api/disconnect",e->{
                e.getRequestBody().readAllBytes();disconnectedWrites.incrementAndGet();e.close();
            });
            upstream.setExecutor(java.util.concurrent.Executors.newCachedThreadPool(r->{var t=new Thread(r);t.setDaemon(true);return t;}));
            upstream.start();
        } catch(Exception e){throw new ExceptionInInitializerError(e);}
    }
    @DynamicPropertySource static void routes(DynamicPropertyRegistry props) {
        props.add("spring.cloud.gateway.routes[0].id",()->"test-upstream");
        props.add("spring.cloud.gateway.routes[0].uri",()->"http://127.0.0.1:"+upstream.getAddress().getPort());
        props.add("spring.cloud.gateway.routes[0].predicates[0]",()->"Path=/api/**");
    }
    @SuppressWarnings("unchecked") void allow() { when(redis.execute(any(),anyList(),anyList())).thenReturn((Flux)Flux.just(1L)); }
    @Test void firstSseFrameArrivesBeforeUpstreamFinishes() {
        allow();long start=System.nanoTime();
        var first=WebClient.create("http://127.0.0.1:"+port).get().uri("/api/stream").retrieve()
            .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>(){}).blockFirst(Duration.ofSeconds(2));
        assertNotNull(first);assertEquals("first",first.data());
        assertTrue(System.nanoTime()-start<Duration.ofSeconds(2).toNanos());
    }
    @Test void requestBodyAndLargeIdsRemainIntactWithoutWriteRetry() {
        allow();int before=writes.get();String body="{\"articleId\":\"9007199254740993\",\"title\":\"中文\"}";
        String result=WebClient.create("http://127.0.0.1:"+port).post().uri("/api/write")
            .header("Content-Type","application/json").bodyValue(body).retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5));
        assertEquals(body,result);assertEquals(before+1,writes.get());
    }
    @Test void connectionLossAfterMutationNeverReplaysThePost() {
        allow();int before=disconnectedWrites.get();
        var status=WebClient.create("http://127.0.0.1:"+port).post().uri("/api/disconnect").bodyValue("mutation")
            .exchangeToMono(response->reactor.core.publisher.Mono.just(response.statusCode().value())).block(Duration.ofSeconds(5));
        assertEquals(503,status);assertEquals(before+1,disconnectedWrites.get());
    }
}
