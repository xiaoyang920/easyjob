package com.easyjob.agent;

import com.easyjob.agent.controller.AgentReadinessController;
import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.agent.security.AgentServiceAuth;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentReadinessTests {
    private static final String KEY = "readiness-test-key-at-least-32-bytes";

    @Test void anonymousOrWrongKeyCannotInvokeRpc() {
        AgentRpcClient rpc = mock(AgentRpcClient.class);
        AgentReadinessController controller = new AgentReadinessController(new AgentServiceAuth(KEY), rpc);
        for (String key : new String[]{null, "wrong"}) {
            assertEquals(HttpStatus.UNAUTHORIZED,
                assertThrows(ResponseStatusException.class, () -> controller.ready(key)).getStatusCode());
        }
        verifyNoInteractions(rpc);
    }

    @Test void reportsSuccessOnlyAfterRpcAndDoesNotExposeOverview() {
        AgentRpcClient rpc = mock(AgentRpcClient.class);
        when(rpc.serviceQuery(1L,"health","","",1,1,"")).thenReturn(java.util.Map.of("status", "ready"));
        AgentReadinessController controller = new AgentReadinessController(new AgentServiceAuth(KEY), rpc);
        assertEquals(java.util.Map.of("status", "ready", "rpc", "ok"), controller.ready(KEY));
        verify(rpc).serviceQuery(1L,"health","","",1,1,"");
        verifyNoMoreInteractions(rpc);
    }

    @Test void failedReadProbeIsNotRetriedInsideControllerOrReportedHealthy() {
        AgentRpcClient rpc = mock(AgentRpcClient.class);
        when(rpc.serviceQuery(1L,"health","","",1,1,"")).thenThrow(new ResponseStatusException(HttpStatus.BAD_GATEWAY));
        AgentReadinessController controller = new AgentReadinessController(new AgentServiceAuth(KEY), rpc);
        assertEquals(HttpStatus.BAD_GATEWAY,
            assertThrows(ResponseStatusException.class, () -> controller.ready(KEY)).getStatusCode());
        verify(rpc).serviceQuery(1L,"health","","",1,1,"");
        verifyNoMoreInteractions(rpc);
    }
}
