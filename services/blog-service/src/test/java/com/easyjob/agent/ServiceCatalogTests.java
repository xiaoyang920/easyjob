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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;

class ServiceCatalogTests {
    @Test void slowRefreshDoesNotBlockCallsAndEmptyHealthWithdrawsImmediately() throws Exception {
        AtomicBoolean slow=new java.util.concurrent.atomic.AtomicBoolean();
        CountDownLatch entered=new java.util.concurrent.CountDownLatch(1);CountDownLatch release=new java.util.concurrent.CountDownLatch(1);
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/",exchange -> {
            boolean health=exchange.getRequestURI().getPath().contains("/health/");
            if(health && slow.get()) { entered.countDown();try { release.await(); }catch(InterruptedException e){Thread.currentThread().interrupt();} }
            String body=!health?"{}":slow.get()?"[]":"[{\"Service\":{\"Address\":\"127.0.0.1\",\"Meta\":{\"rpc_port\":\"50052\"}}}]";
            byte[] bytes=body.getBytes();exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });server.start();
        ServiceCatalog catalog=new ServiceCatalog(new ObjectMapper(),true,"http://127.0.0.1:"+server.getAddress().getPort(),"","127.0.0.1",8080,20881,"slow-test");
        try(ExecutorService executor=java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            catalog.ready();slow.set(true);Future<?> refresh=executor.submit(catalog::refresh);
            assertTrue(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));
            try { assertTimeoutPreemptively(Duration.ofMillis(500),() -> {
                for(int i=0;i<1000;i++) assertEquals("127.0.0.1:50052",catalog.agentTarget(i));
            }); } finally { release.countDown(); }
            refresh.get(3,java.util.concurrent.TimeUnit.SECONDS);
            assertThrows(IllegalStateException.class,() -> catalog.agentTarget(7));
        } finally { release.countDown();catalog.close();server.stop(0); }
    }
    @Test void registrationAndHealthDiscoveryExpireWithoutDirectFallback() throws Exception {
        CopyOnWriteArrayList<String> requests=new CopyOnWriteArrayList<String>();
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestURI()+":"+new String(exchange.getRequestBody().readAllBytes()));
            String body=exchange.getRequestURI().getPath().contains("/health/")?
                "[{\"Service\":{\"Address\":\"127.0.0.1\",\"Meta\":{\"rpc_port\":\"50052\"}}}]":"{}";
            byte[] bytes=body.getBytes();exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.start();
        AtomicLong clock=new AtomicLong(System.nanoTime());
        ServiceCatalog catalog=new ServiceCatalog(new ObjectMapper(),true,"http://127.0.0.1:"+server.getAddress().getPort(),"",
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
