package com.easyjob.service;

import com.easyjob.mapper.AdminAgentMetricsMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.Map;

class DeliveryMetricsTests {
    @Test void browserSamplesAreIndependentFromModelUsageAndMissingIsNotZero() {
        AdminAgentMetricsMapper store=mock(AdminAgentMetricsMapper.class);
        when(store.findMetrics(any(),any(),eq("business"))).thenReturn(List.of(
            Map.of("status","succeeded","delivery","{\"first_answer_ms\":1200}"),
            Map.of("status","failed","delivery","{\"first_answer_ms\":2400}"),
            Map.of("status","succeeded","delivery","{}")));
        when(store.findStages(any(),any(),eq("business"))).thenReturn(List.of(Map.of("name","final_gate","count",2,"p95_ms",900)));
        AdminAgentMetricsService service=new AdminAgentMetricsService(store,mock(AdminConsoleService.class),new ObjectMapper());
        Map<String, Object> result=service.report(7L,7,"business");
        assertEquals(2,result.get("firstAnswerSamples"));assertEquals(1200L,result.get("firstAnswerP50Ms"));assertEquals(2400L,result.get("firstAnswerP95Ms"));
        assertEquals(0L,result.get("measuredInputTokens"));assertEquals(1,((List<?>)result.get("stages")).size());
    }
    @Test void emptySamplesRemainUnknown() {
        AdminAgentMetricsService service=new AdminAgentMetricsService(mock(AdminAgentMetricsMapper.class),mock(AdminConsoleService.class),new ObjectMapper());
        Map<String, Object> result=service.report(7L,7,"business");assertNull(result.get("firstAnswerP95Ms"));assertEquals(0,result.get("firstAnswerSamples"));
    }
    @Test void normallySettledButIncompleteDeliveriesAreNotSuccessfulTasks() {
        AdminAgentMetricsMapper store=mock(AdminAgentMetricsMapper.class);
        when(store.countStates(any(),any(),eq("business"))).thenReturn(List.of(
            Map.of("status","succeeded","count",3L,"incomplete",2L),
            Map.of("status","failed","count",1L),
            Map.of("status","cancelled","count",1L),
            Map.of("status","expired","count",1L),
            Map.of("status","running","count",1L)));
        Map<String, Object> result=new AdminAgentMetricsService(store,mock(AdminConsoleService.class),new ObjectMapper()).report(7L,7,"business");
        assertEquals(7L,result.get("totalRuns"));
        assertEquals(6L,result.get("finishedRuns"));
        assertEquals(3L,result.get("executionSucceededRuns"));
        assertEquals(2L,result.get("incompleteRuns"));
        assertEquals(1L,result.get("succeededRuns"));
        assertEquals(100.0/6,(Double)result.get("successRate"),0.0001);
    }
}
