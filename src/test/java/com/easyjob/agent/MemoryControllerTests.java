package com.easyjob.agent;

import com.easyjob.agent.controller.MemoryController;
import com.easyjob.agent.service.AgentService;
import com.easyjob.utils.UserContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.Map;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class MemoryControllerTests {
    @AfterEach void clear() { UserContext.clear(); }
    @Test void identityAlwaysComesFromAuthenticatedContext() throws Exception {
        var agent = mock(AgentService.class);
        UserContext.setUserId(7L);
        when(agent.memoryRequest(7L, HttpMethod.GET, "/memory?limit=30&kind=all", null)).thenReturn(Map.of("memories", java.util.List.of()));
        var mvc = MockMvcBuilders.standaloneSetup(new MemoryController(agent)).build();
        mvc.perform(get("/api/agent/memory").param("user_id", "8")).andExpect(status().isOk()).andExpect(jsonPath("$.code").value(200));
        verify(agent).memoryRequest(7L, HttpMethod.GET, "/memory?limit=30&kind=all", null);
    }
    @Test void invalidDeleteVersionNeverReachesPython() throws Exception {
        var agent = mock(AgentService.class);
        UserContext.setUserId(7L);
        var mvc = MockMvcBuilders.standaloneSetup(new MemoryController(agent)).build();
        mvc.perform(delete("/api/agent/memory/records/19").param("version", "../../other")).andExpect(status().isBadRequest());
        mvc.perform(get("/api/agent/memory").param("limit", "1000")).andExpect(status().isBadRequest());
        mvc.perform(get("/api/agent/memory").param("kind", "event&user_id=8")).andExpect(status().isBadRequest());
        verifyNoInteractions(agent);
    }
}
