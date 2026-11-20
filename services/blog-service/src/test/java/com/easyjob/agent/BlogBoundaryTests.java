package com.easyjob.agent;

import com.easyjob.agent.service.AgentBlogQueryService;
import com.easyjob.agent.rpc.RpcValues;
import com.easyjob.mapper.AgentBlogQueryMapper;
import com.easyjob.rpc.v1.BlogQuery;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.rpc.v1.BlogQuery.Builder;

class BlogBoundaryTests {
    private BlogQuery repair(Map<String,Object> snapshot) {
        return BlogQuery.newBuilder().setKind("article_repair").setTargetId(42)
            .setExpected(RpcValues.encode(snapshot).getObject()).build();
    }
    @Test void changedSnapshotCannotEnqueueStaleIndexRepair() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);AgentBlogQueryService service=new AgentBlogQueryService(store);
        when(store.lockArticle(42)).thenReturn(Map.of("content","new"));
        assertEquals(false,service.maintenance(repair(Map.of("content","old"))));
        verify(store,never()).repair(anyLong(),anyString());
    }
    @Test void pendingOrDeadIndexJobDoesNotBypassQueueRetryPolicy() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);AgentBlogQueryService service=new AgentBlogQueryService(store);
        when(store.lockArticle(42)).thenReturn(Map.of("content","same"));when(store.activeJobs(42)).thenReturn(1);
        assertEquals(false,service.maintenance(repair(Map.of("content","same"))));
        verify(store,never()).repair(anyLong(),anyString());
    }
    @Test void orphanRepairCannotDeleteAnArticleThatBecamePublic() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);AgentBlogQueryService service=new AgentBlogQueryService(store);
        when(store.lockArticle(42)).thenReturn(Map.of("status",1,"deleted",0));
        assertEquals(false,service.maintenance(repair(Map.of())));
        verify(store,never()).repair(anyLong(),anyString());
    }
    @Test void queryNamesAndBatchSizesAreBounded() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);AgentBlogQueryService service=new AgentBlogQueryService(store);
        assertThrows(ResponseStatusException.class,()->service.read(BlogQuery.newBuilder().setKind("raw_sql").build()));
        Builder query=BlogQuery.newBuilder().setKind("published");for(int i=1;i<=129;i++)query.addIds(i);
        assertThrows(ResponseStatusException.class,()->service.read(query.build()));verifyNoInteractions(store);
    }
}
