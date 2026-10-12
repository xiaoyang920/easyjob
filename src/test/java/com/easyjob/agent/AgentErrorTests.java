package com.easyjob.agent;

import com.easyjob.agent.controller.AgentController;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentService;
import com.easyjob.config.GlobalExceptionHandler;
import com.easyjob.utils.UserContext;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentErrorTests {
    @AfterEach void clearUser() { UserContext.clear(); }

    private AgentService service() {
        var service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        return service;
    }

    @Test void staleApprovalPreserves409AndDoesNotExposeUpstreamBody() {
        var service = service();
        var server = MockRestServiceServer.bindTo((RestTemplate) ReflectionTestUtils.getField(service, "restTemplate")).build();
        server.expect(requestTo("http://localhost:8000/chat/resume"))
                .andRespond(withStatus(HttpStatus.CONFLICT).contentType(MediaType.APPLICATION_JSON)
                        .body("{\"detail\":\"private-upstream-payload\"}"));
        var error = assertThrows(ResponseStatusException.class,
                () -> service.chatResume(11L, 7L, "approve", "run", "old-hash"));
        assertEquals(409, error.getStatusCode().value());
        assertTrue(error.getReason().contains("重新加载"));
        assertFalse(error.getReason().contains("private-upstream"));
        server.verify();
    }

    @Test void upstreamFailureIs502WithSafeMessage() {
        var service = service();
        var server = MockRestServiceServer.bindTo((RestTemplate) ReflectionTestUtils.getField(service, "restTemplate")).build();
        server.expect(requestTo("http://localhost:8000/chat/resume"))
                .andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR).body("internal stack"));
        var error = assertThrows(ResponseStatusException.class,
                () -> service.chatResume(11L, 7L, "approve", "run", "hash"));
        assertEquals(502, error.getStatusCode().value());
        assertFalse(error.getReason().contains("internal stack"));
        server.verify();
    }

    @Test void synchronousControllerReturnsHttpAndBusiness409() throws Exception {
        UserContext.setUserId(7L);
        var service = mock(AgentService.class);
        when(service.chatResume(anyLong(), anyLong(), anyString(), anyString(), anyString(), isNull()))
                .thenThrow(new ResponseStatusException(HttpStatus.CONFLICT, "草稿版本已更新，请重新加载"));
        var controller = new AgentController();
        ReflectionTestUtils.setField(controller, "agentService", service);
        var mvc = MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler()).build();
        mvc.perform(post("/api/agent/chat/resume").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conversationId\":11,\"action\":\"approve\",\"runId\":\"run\",\"draftHash\":\"old\"}"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value(409))
                .andExpect(jsonPath("$.message").value("草稿版本已更新，请重新加载"));
    }

    @Test void streamingControllerReturnsJsonConflictBeforeStreamStarts() throws Exception {
        UserContext.setUserId(7L);
        var service = mock(AgentService.class);
        when(service.chatResumeStream(anyLong(), anyLong(), anyString(), anyString(), anyString(), isNull()))
                .thenReturn(Flux.error(new ResponseStatusException(HttpStatus.CONFLICT, "审批已失效，请重新加载")));
        var controller = new AgentController();
        ReflectionTestUtils.setField(controller, "agentService", service);
        var mvc = MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new GlobalExceptionHandler()).build();
        var pending = mvc.perform(post("/api/agent/chat/resume/stream").accept(MediaType.TEXT_EVENT_STREAM)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"conversationId\":11,\"action\":\"approve\",\"runId\":\"run\",\"draftHash\":\"old\"}"))
                .andExpect(request().asyncStarted()).andReturn();
        mvc.perform(asyncDispatch(pending)).andExpect(status().isConflict())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value(409));
    }

    @Test void recoveryUsesAuthenticatedIdentityAndKeepsUpstreamConflict() throws Exception {
        var upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var authenticated = new java.util.concurrent.atomic.AtomicBoolean();
        String runId = "ae0bd008-98cf-4018-b809-e80860386b01";
        upstream.createContext("/runs/" + runId + "/recover", exchange -> {
            exchange.getRequestBody().readAllBytes();
            authenticated.set("POST".equals(exchange.getRequestMethod())
                    && "7".equals(exchange.getRequestHeaders().getFirst("X-Agent-User"))
                    && exchange.getRequestHeaders().getFirst("X-Agent-Key") != null);
            byte[] body = "{\"detail\":\"cannot recover\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(409, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        upstream.start();
        try {
            var service = service();
            ReflectionTestUtils.setField(service, "pythonUrl", "http://127.0.0.1:" + upstream.getAddress().getPort());
            var error = assertThrows(ResponseStatusException.class, () -> service.recoverRun(runId, 7L).blockLast(Duration.ofSeconds(5)));
            assertEquals(409, error.getStatusCode().value());
            assertTrue(authenticated.get());
            assertThrows(ResponseStatusException.class, () -> service.recoverRun("invalid/path", 7L));
        } finally { upstream.stop(0); }
    }

    @Test void realWebClientStreamingErrorKeeps409() throws Exception {
        var upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        upstream.createContext("/chat/resume/stream", exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] body = "{\"detail\":\"stale draft\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(409, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        upstream.start();
        try {
            var service = service();
            ReflectionTestUtils.setField(service, "pythonUrl", "http://127.0.0.1:" + upstream.getAddress().getPort());
            var error = assertThrows(ResponseStatusException.class, () ->
                    service.chatResumeStream(11L, 7L, "approve", "run", "old").blockLast(Duration.ofSeconds(5)));
            assertEquals(409, error.getStatusCode().value());
        } finally {
            upstream.stop(0);
        }
    }
}
