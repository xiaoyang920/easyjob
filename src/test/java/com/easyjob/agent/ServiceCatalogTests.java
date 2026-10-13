package com.easyjob.agent;

import com.easyjob.agent.rpc.ServiceCatalog;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.ArrayList;
import static org.junit.jupiter.api.Assertions.*;

class ServiceCatalogTests {
    @Test void registrationAndHealthDiscoveryExpireWithoutDirectFallback() throws Exception {
        var requests=new ArrayList<String>();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestURI()+":"+new String(exchange.getRequestBody().readAllBytes()));
            String body=exchange.getRequestURI().getPath().contains("/health/")?
                "[{\"Service\":{\"Address\":\"127.0.0.1\",\"Meta\":{\"rpc_port\":\"50052\"}}}]":"{}";
            byte[] bytes=body.getBytes();exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.start();
        var catalog=new ServiceCatalog(new ObjectMapper(),true,"http://127.0.0.1:"+server.getAddress().getPort(),"",
            "127.0.0.1",8080,20881,"test-blog");
        try {
            catalog.ready();assertEquals("127.0.0.1:50052",catalog.agentTarget(7));
            assertTrue(requests.stream().anyMatch(s->s.contains("20881") && s.contains("30s")));
            server.stop(0);
            var field=ServiceCatalog.class.getDeclaredField("refreshed");field.setAccessible(true);
            field.setLong(catalog,System.nanoTime()-Duration.ofSeconds(6).toNanos());
            assertEquals("127.0.0.1:50052",catalog.agentTarget(7));
            field.setLong(catalog,System.nanoTime()-Duration.ofSeconds(31).toNanos());
            assertThrows(IllegalStateException.class,()->catalog.agentTarget(7));
        } finally {server.stop(0);catalog.close();}
    }
}
