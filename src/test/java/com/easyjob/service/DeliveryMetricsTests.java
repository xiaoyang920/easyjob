package com.easyjob.service;

import com.easyjob.agent.controller.DeliveryMetricsController;
import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.AdminAgentMetricsMapper;
import com.easyjob.utils.UserContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class DeliveryMetricsTests {
    @Test void browserSamplesAreIndependentFromModelUsageAndMissingIsNotZero() {
        var store=mock(AdminAgentMetricsMapper.class);
        when(store.findMetrics(any(),any(),eq("business"))).thenReturn(List.of(
            Map.of("status","succeeded","delivery","{\"first_answer_ms\":1200}"),
            Map.of("status","failed","delivery","{\"first_answer_ms\":2400}"),
            Map.of("status","succeeded","delivery","{}")));
        when(store.findStages(any(),any(),eq("business"))).thenReturn(List.of(Map.of("name","final_gate","count",2,"p95_ms",900)));
        var service=new AdminAgentMetricsService(store,mock(AdminConsoleService.class),new ObjectMapper());
        var result=service.report(7L,7,"business");
        assertEquals(2,result.get("firstAnswerSamples"));assertEquals(1200L,result.get("firstAnswerP50Ms"));assertEquals(2400L,result.get("firstAnswerP95Ms"));
        assertEquals(0L,result.get("measuredInputTokens"));assertEquals(1,((List<?>)result.get("stages")).size());
    }
    @Test void emptySamplesRemainUnknown() {
        var service=new AdminAgentMetricsService(mock(AdminAgentMetricsMapper.class),mock(AdminConsoleService.class),new ObjectMapper());
        var result=service.report(7L,7,"business");assertNull(result.get("firstAnswerP95Ms"));assertEquals(0,result.get("firstAnswerSamples"));
    }
    @Test void deliveryControllerRejectsMissingIdentityAndInvalidSamples() {
        var rpc=mock(AgentRpcClient.class);var controller=new DeliveryMetricsController(rpc);
        UserContext.clear();
        assertEquals(401,assertThrows(BusinessException.class,()->controller.record(UUID.randomUUID().toString(),new DeliveryMetricsController.Sample(1L))).getCode());
        UserContext.setUserId(7L);
        try {
            assertThrows(BusinessException.class,()->controller.record("bad",new DeliveryMetricsController.Sample(1L)));
            assertThrows(BusinessException.class,()->controller.record(UUID.randomUUID().toString(),new DeliveryMetricsController.Sample(null)));
            assertThrows(BusinessException.class,()->controller.record(UUID.randomUUID().toString(),new DeliveryMetricsController.Sample(-1L)));
            verifyNoInteractions(rpc);
        } finally { UserContext.clear(); }
    }
}
