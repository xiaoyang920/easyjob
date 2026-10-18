package com.easyjob.agent.tool;

import com.alibaba.fastjson2.JSONObject;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class DeepSeekSearchToolTests {
    private HttpServer server;
    private DeepSeekSearchTool tool;
    private JSONObject received;
    private String authorization;
    private int status = 200;
    private String response = "{\"results\":[]}";
    private final AtomicInteger calls = new AtomicInteger();

    @BeforeEach void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/tools/search", exchange -> {
            calls.incrementAndGet();
            authorization = exchange.getRequestHeaders().getFirst("Authorization");
            received = JSONObject.parseObject(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] body = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, body.length);
            try (var out = exchange.getResponseBody()) { out.write(body); }
        });
        server.start();
        tool = new DeepSeekSearchTool("test-key", "http://127.0.0.1:" + server.getAddress().getPort() + "/v1/", 5, true);
    }

    @AfterEach void stop() { server.stop(0); }

    @Test void usesDeepSeekRequestAndKeepsReturnedBody() {
        response = "{\"results\":[{\"title\":\"Docs\",\"url\":\"https://spring.io/\",\"content\":\"real body\",\"summary\":\"short summary\"}]}";
        String output = tool.webSearch("Spring Boot", null);
        assertEquals("Bearer test-key", authorization);
        assertEquals("Spring Boot", received.getString("query"));
        assertEquals(5, received.getIntValue("count"));
        assertTrue(received.getBooleanValue("need_content"));
        assertFalse(received.containsKey("freshness"));
        assertTrue(output.contains("real body"));
        assertTrue(output.contains("返回的网页正文"));
        assertFalse(output.contains("short summary"));
    }

    @Test void summaryIsNotPresentedAsPageBody() {
        response = "{\"results\":[{\"title\":\"Docs\",\"url\":\"https://spring.io/\",\"content\":\"\",\"summary\":\"summary only\"}]}";
        String output = tool.webSearch("q", null);
        assertTrue(output.contains("搜索摘要（未取得网页正文）"));
        assertTrue(output.contains("summary only"));
    }

    @Test void freshnessTranslatesToSupportedSearchSyntax() {
        tool.webSearch("Spring", "week");
        assertTrue(received.getString("query").startsWith("Spring after:"));
    }

    @Test void rejectsOverlongQueryWithoutDroppingConditions() {
        assertTrue(tool.webSearch("中".repeat(129), null).contains("128"));
        assertTrue(tool.webSearch("x".repeat(120), "day").contains("128"));
        assertEquals(0, calls.get());
        tool.webSearch("😀".repeat(128), null);
        assertEquals(1, calls.get());
    }

    @Test void errorsDoNotLeakProviderResponse() {
        for (int code : new int[]{401, 402, 429, 500}) {
            status = code;
            response = "private provider body test-key";
            String output = tool.webSearch("q", null);
            assertFalse(output.contains("private"));
            assertFalse(output.contains("test-key"));
            assertTrue(output.contains("DeepSeek"));
        }
        assertEquals(4, calls.get());
    }

    @Test void malformedResponseIsNotReportedAsEmptySearch() {
        response = "{\"code\":200,\"data\":{}}";
        assertTrue(tool.webSearch("q", null).contains("格式异常"));
        response = "{\"results\":[]}";
        assertTrue(tool.webSearch("q", null).contains("未找到"));
    }
}
