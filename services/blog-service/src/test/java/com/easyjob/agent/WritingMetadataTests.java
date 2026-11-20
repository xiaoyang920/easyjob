package com.easyjob.agent;

import com.easyjob.agent.service.AgentBlogQueryService;
import com.easyjob.mapper.AgentBlogQueryMapper;
import com.easyjob.rpc.v1.BlogQuery;
import com.easyjob.rpc.v1.Identity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class WritingMetadataTests {
    @Test void privateMetadataUsesAuthenticatedAuthorAndExactLongIdentifiers() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);
        BlogQuery query=BlogQuery.newBuilder().setIdentity(Identity.newBuilder().setUserId(7)).setKind("writing_metadata").addIds(9007199254740993L).build();
        new AgentBlogQueryService(store).read(query);
        verify(store).writingMetadata(7,List.of(9007199254740993L));
        verify(store,never()).published(anyList());
    }
    @Test void privateMetadataRejectsInvalidIdsBeforeQuerying() {
        AgentBlogQueryMapper store=mock(AgentBlogQueryMapper.class);
        assertThrows(org.springframework.web.server.ResponseStatusException.class,()->new AgentBlogQueryService(store).read(
            BlogQuery.newBuilder().setKind("writing_metadata").addIds(-1).build()));
        verifyNoInteractions(store);
    }
}
