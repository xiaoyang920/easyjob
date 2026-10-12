package com.easyjob.agent;

import com.easyjob.agent.service.AgentService;
import com.easyjob.agent.service.AiConversationService;
import com.easyjob.agent.controller.AgentController;
import com.easyjob.agent.param.AiChatParam;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.utils.UserContext;
import com.alibaba.fastjson2.JSON;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.mock.http.client.MockClientHttpRequest;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import reactor.core.publisher.Flux;
import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;
import static org.mockito.Mockito.*;

class AgentProxyTests {
    @Test
    void pagedHistoryPreservesStableIdsAndForwardsOnlyAuthenticatedIdentity() {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/messages?user_id=7&limit=20&around=9007199254740993"))
                .andExpect(header("X-Agent-User", "7"))
                .andRespond(withSuccess("{\"data\":{\"items\":[{\"itemId\":\"message:9007199254740993\",\"turnId\":\"9007199254740993\",\"agentEvents\":[{\"status\":\"error\"}]}],\"hasOlder\":true}}", MediaType.APPLICATION_JSON));
        var result = service.historyPage(11L, 20, null, null, 9007199254740993L);
        var first = (java.util.Map<?, ?>) ((java.util.List<?>) result.get("items")).getFirst();
        assertEquals("9007199254740993", first.get("turnId"));
        assertEquals("message:9007199254740993", first.get("itemId"));
        assertNotNull(first.get("agentEvents"));
        server.verify();
    }

    @Test
    void questionIndexForwardsSnapshotAndKeysetCursor() {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/questions?user_id=7&limit=200&after=21&snapshot=99"))
                .andExpect(header("X-Agent-User", "7"))
                .andRespond(withSuccess("{\"data\":{\"items\":[],\"snapshot\":\"99\",\"hasMore\":false}}", MediaType.APPLICATION_JSON));
        assertEquals("99", service.questionIndex(11L, 200, 21L, 99L).get("snapshot"));
        server.verify();
    }

    @Test
    void globalRunOverviewUsesAuthenticatedUserWithoutForwardingClientIdentity() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/run-overview"))
                .andExpect(method(HttpMethod.GET)).andExpect(header("X-Agent-User", "7"))
                .andRespond(withSuccess("{\"items\":[{\"conversationId\":\"11\",\"status\":\"running\"}],\"serverTime\":\"2026-10-05T11:00:00Z\"}", MediaType.APPLICATION_JSON));
        assertEquals(1, ((java.util.List<?>) service.runOverview(7L).get("items")).size());
        server.verify();
    }
    @Test
    void conversationRunIsDiscoveredByConversationAndAuthenticatedIdentity() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/run"))
                .andExpect(method(HttpMethod.GET)).andExpect(header("X-Agent-User", "7"))
                .andRespond(withSuccess("{\"runId\":\"owned-run\",\"status\":\"running\"}", MediaType.APPLICATION_JSON));
        assertEquals("owned-run", service.conversationRun(11L, 7L).get("runId"));
        server.verify();
    }

    @Test
    void conversationWithNoRunReturnsNullRatherThanParsingAnEmptyMap() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/run"))
                .andRespond(withSuccess("null", MediaType.APPLICATION_JSON));
        assertNull(service.conversationRun(11L, 7L));
        server.verify();
    }
    @AfterEach
    void clearUser() {
        UserContext.clear();
    }

    @Test
    void newConversationAllowsNullIdAndKeepsMetadata() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/chat"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(header("X-Agent-User", "7"))
                .andExpect(header("X-Agent-Key", "offline-service-key-32-bytes-long!!"))
                .andExpect(request -> {
                    var body = JSON.parseObject(((MockClientHttpRequest) request).getBodyAsString());
                    assertTrue(body.containsKey("conversation_id"));
                    assertNull(body.get("conversation_id"));
                    assertFalse(body.containsKey("origin_article_id"));
                    assertEquals(7L, body.getLong("user_id"));
                })
                .andRespond(withSuccess("{\"conversationId\":\"11\",\"reply\":\"saved\",\"draftArticleId\":\"99\",\"citations\":[{\"id\":\"1\"}]}", MediaType.APPLICATION_JSON));
        var response = service.chat(null, 7L, "hello", null);
        assertEquals("99", response.getDraftArticleId());
        assertEquals(1, response.getCitations().size());
        server.verify();
    }

    @Test
    void articleChatForwardsOriginWithoutLosingRequestIdentity() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/chat"))
                .andExpect(header("X-Agent-User", "7"))
                .andExpect(request -> {
                    var body = JSON.parseObject(((MockClientHttpRequest) request).getBodyAsString());
                    assertEquals(123L, body.getLong("origin_article_id"));
                    assertEquals(11L, body.getLong("conversation_id"));
                    assertEquals("request-1", body.getString("request_id"));
                    assertEquals("compare with another article", body.getString("message"));
                })
                .andRespond(withSuccess("{\"conversationId\":\"11\",\"reply\":\"ok\"}", MediaType.APPLICATION_JSON));
        service.chat(11L, 7L, "compare with another article", null, "request-1", 123L);
        server.verify();
    }

    @Test
    void invalidOriginNeverStartsNormalOrStreamingRequest() {
        AgentService service = new AgentService();
        assertThrows(IllegalArgumentException.class, () -> service.chat(null, 7L, "hello", null, "r", 0L));
        assertThrows(IllegalArgumentException.class, () -> service.chatStream(null, 7L, "hello", null, "r", -1L));
    }

    @Test
    void articleListKeepsCursorAndAuthenticatedUserAndMapsOriginMetadata() {
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations?user_id=7&limit=10&scope=article&last_update_time=2026-10-02T08:00&last_id=88&origin_article_id=123"))
                .andExpect(header("X-Agent-User", "7"))
                .andExpect(header("X-Agent-Key", "offline-service-key-32-bytes-long!!"))
                .andRespond(withSuccess("{\"data\":[{\"conversationId\":\"11\",\"originArticleId\":\"123\",\"originArticleTitle\":\"Spring Boot\"}]}", MediaType.APPLICATION_JSON));
        var rows = service.getUserConversationsWithCursor(7L, LocalDateTime.of(2026, 10, 2, 8, 0), 88L, 10, "article", 123L);
        assertEquals(123L, rows.getFirst().getOriginArticleId());
        assertEquals("Spring Boot", rows.getFirst().getOriginArticleTitle());
        server.verify();
    }

    @Test
    void legacyListDefaultsToAllScopes() {
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations?user_id=7&limit=10&scope=all"))
                .andRespond(withSuccess("{\"data\":[]}", MediaType.APPLICATION_JSON));
        assertTrue(service.getUserConversationsWithCursor(7L, null, null, 10).isEmpty());
        server.verify();
    }

    @Test
    void invalidListScopeNeverReachesPython() {
        AiConversationService service = new AiConversationService();
        assertThrows(IllegalArgumentException.class, () -> service.getUserConversationsWithCursor(7L, null, null, 10, "invalid", null));
        assertThrows(IllegalArgumentException.class, () -> service.getUserConversationsWithCursor(7L, null, null, 10, "article", -123L));
        assertThrows(IllegalArgumentException.class, () -> service.getUserConversationsWithCursor(7L, null, null, 10, "general", 123L));
    }

    @Test
    void metadataUsesConfiguredAgentUrlAndAuthenticatedUser() {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "pythonUrl", "http://agent.internal:8001");
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://agent.internal:8001/conversations/11?user_id=7"))
                .andExpect(header("X-Agent-User", "7"))
                .andExpect(header("X-Agent-Key", "offline-service-key-32-bytes-long!!"))
                .andRespond(withSuccess("{\"data\":{\"conversationId\":\"11\",\"originArticleId\":\"123\"}}", MediaType.APPLICATION_JSON));
        assertEquals(123L, service.getConversation(11L).getOriginArticleId());
        server.verify();
    }

    @Test
    void controllerForwardsArticleOriginAndCurrentUserOnBothChatPaths() {
        UserContext.setUserId(7L);
        AgentService service = mock(AgentService.class);
        AgentController controller = new AgentController();
        ReflectionTestUtils.setField(controller, "agentService", service);
        AiChatParam param = new AiChatParam();
        param.setConversationId(11L);
        param.setOriginArticleId(123L);
        param.setMessage("Compare articles");
        param.setRequestId("request-1");
        when(service.chatStream(11L, 7L, "Compare articles", null, "request-1", 123L)).thenReturn(Flux.just("done"));
        controller.chat(param);
        var response = new MockHttpServletResponse();
        assertEquals("done", controller.chatStream(param, response).blockLast());
        verify(service).chat(11L, 7L, "Compare articles", null, "request-1", 123L);
        verify(service).chatStream(11L, 7L, "Compare articles", null, "request-1", 123L);
        assertEquals("no-cache", response.getHeader("Cache-Control"));
        assertEquals("no", response.getHeader("X-Accel-Buffering"));
    }

    @Test
    void cancellationForwardsAuthenticatedUser() {
        AgentService service = new AgentService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/chat/11/cancel?user_id=7"))
                .andExpect(method(HttpMethod.POST)).andRespond(withSuccess());
        service.cancelChat(11L, 7L);
        server.verify();
    }

    @Test
    void historyAndDeletionForwardAuthenticatedUser() {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/messages?user_id=7"))
                .andExpect(method(HttpMethod.GET)).andRespond(withSuccess("{\"data\":[]}", MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://localhost:8000/conversations/11?user_id=7"))
                .andExpect(method(HttpMethod.DELETE)).andRespond(withSuccess());
        service.getContext(11L);
        service.clearContext(11L);
        server.verify();
    }

    @Test
    void failedHistoryKeepsRunIdentityActivitiesAndOriginalClock() throws Exception {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        RestTemplate client = (RestTemplate) ReflectionTestUtils.getField(service, "restTemplate");
        MockRestServiceServer server = MockRestServiceServer.bindTo(client).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/messages?user_id=7"))
                .andRespond(withSuccess("""
                    {"data":[{"role":"user","content":"继续","messageId":"123"},
                    {"role":"assistant","content":"本次处理失败","runId":"failed-run","runStatus":"failed",
                    "runStartedAt":"2026-10-11T01:00:00Z","runFinishedAt":"2026-10-11T01:00:20Z",
                    "recoverable":false,"agentEvents":[{"kind":"activity","id":"search","status":"done"}]}]}
                    """, MediaType.APPLICATION_JSON));
        var messages = service.getContext(11L);
        assertEquals(123L, messages.get(0).getMessageId());
        var failure = messages.get(1);
        assertEquals("failed-run", failure.getRunId());
        assertEquals("failed", failure.getRunStatus());
        assertEquals("2026-10-11T01:00:20Z", failure.getRunFinishedAt());
        assertEquals(false, failure.getRecoverable());
        assertEquals("done", failure.getAgentEvents().get(0).get("status"));
        String encoded = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(messages);
        assertTrue(encoded.contains("\"runId\":\"failed-run\""));
        assertTrue(encoded.contains("\"agentEvents\""));
        server.verify();
    }

    @Test
    void inaccessibleHistoryKeeps404WithoutLeakingUpstreamPayload() {
        UserContext.setUserId(7L);
        AiConversationService service = new AiConversationService();
        ReflectionTestUtils.setField(service, "serviceAuth", new AgentServiceAuth("offline-service-key-32-bytes-long!!"));
        var server = MockRestServiceServer.bindTo((RestTemplate) ReflectionTestUtils.getField(service, "restTemplate")).build();
        server.expect(requestTo("http://localhost:8000/conversations/11/messages?user_id=7"))
                .andRespond(org.springframework.test.web.client.response.MockRestResponseCreators
                        .withStatus(org.springframework.http.HttpStatus.NOT_FOUND).body("private-upstream-detail"));
        var error = assertThrows(org.springframework.web.server.ResponseStatusException.class, () -> service.getContext(11L));
        assertEquals(404, error.getStatusCode().value());
        assertFalse(error.getReason().contains("private-upstream-detail"));
        server.verify();
    }
}
