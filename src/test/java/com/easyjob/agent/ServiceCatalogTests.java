package com.easyjob.agent;

import com.easyjob.agent.rpc.ServiceCatalog;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;
import static org.junit.jupiter.api.Assertions.*;

class ServiceCatalogTests {
    @Test void slowRefreshDoesNotBlockCallsAndEmptyHealthWithdrawsImmediately() throws Exception {
        var slow=new java.util.concurrent.atomic.AtomicBoolean();
        var entered=new java.util.concurrent.CountDownLatch(1);var release=new java.util.concurrent.CountDownLatch(1);
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/",exchange -> {
            boolean health=exchange.getRequestURI().getPath().contains("/health/");
            if(health && slow.get()) { entered.countDown();try { release.await(); }catch(InterruptedException e){Thread.currentThread().interrupt();} }
            String body=!health?"{}":slow.get()?"[]":"[{\"Service\":{\"Address\":\"127.0.0.1\",\"Meta\":{\"rpc_port\":\"50052\"}}}]";
            byte[] bytes=body.getBytes();exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });server.start();
        var catalog=new ServiceCatalog(new ObjectMapper(),true,"http://127.0.0.1:"+server.getAddress().getPort(),"","127.0.0.1",8080,20881,"slow-test");
        try(var executor=java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            catalog.ready();slow.set(true);var refresh=executor.submit(catalog::refresh);
            assertTrue(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));
            try { assertTimeoutPreemptively(Duration.ofMillis(500),() -> {
                for(int i=0;i<1000;i++) assertEquals("127.0.0.1:50052",catalog.agentTarget(i));
            }); } finally { release.countDown(); }
            refresh.get(3,java.util.concurrent.TimeUnit.SECONDS);
            assertThrows(IllegalStateException.class,() -> catalog.agentTarget(7));
        } finally { release.countDown();catalog.close();server.stop(0); }
    }
    @Test void registrationAndHealthDiscoveryExpireWithoutDirectFallback() throws Exception {
        var requests=new CopyOnWriteArrayList<String>();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestURI()+":"+new String(exchange.getRequestBody().readAllBytes()));
            String body=exchange.getRequestURI().getPath().contains("/health/")?
                "[{\"Service\":{\"Address\":\"127.0.0.1\",\"Meta\":{\"rpc_port\":\"50052\"}}}]":"{}";
            byte[] bytes=body.getBytes();exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.start();
        var clock=new AtomicLong(System.nanoTime());
        var catalog=new ServiceCatalog(new ObjectMapper(),true,"http://127.0.0.1:"+server.getAddress().getPort(),"",
            "127.0.0.1",8080,20881,"test-blog") { @Override protected long now() { return clock.get(); } };
        try {
            catalog.ready();assertEquals("127.0.0.1:50052",catalog.agentTarget(7));
            assertTrue(requests.stream().anyMatch(s->s.contains("20881") && s.contains("30s")));
            server.stop(0);
            clock.addAndGet(Duration.ofSeconds(6).toNanos());
            assertEquals("127.0.0.1:50052",catalog.agentTarget(7));
            clock.addAndGet(Duration.ofSeconds(25).toNanos());
            assertThrows(IllegalStateException.class,()->catalog.agentTarget(7));
        } finally {server.stop(0);catalog.close();}
    }
}
