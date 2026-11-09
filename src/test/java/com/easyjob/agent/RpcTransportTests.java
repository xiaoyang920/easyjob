package com.easyjob.agent;

import com.easyjob.agent.rpc.*;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.rpc.v1.*;
import com.easyjob.service.ArticleRevisionService;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.agent.rpc.BlogRpcProvider;
import com.easyjob.rpc.v1.AgentRpc;
import com.easyjob.rpc.v1.DraftRequest;
import java.lang.Object;
import java.util.LinkedHashMap;

class RpcTransportTests {
    static final String KEY = "rpc-test-service-key-at-least-32-bytes";
    static final long BIG = 9007199254740993L;
    @Test void valuesPreserveLongIdsAndEmptyCollections() {
        LinkedHashMap<String, Object> value = new LinkedHashMap<String,java.lang.Object>();
        value.put("id",BIG); value.put("null",null); value.put("bool",true);
        value.put("items",List.of()); value.put("nested",Map.of("text","中文"));
        assertEquals(value, RpcValues.decode(RpcValues.encode(value)));
        assertThrows(IllegalArgumentException.class, () -> RpcValues.encode(Double.NaN));
    }
    @Test void providerAuthenticatesBeforeBusinessServiceAndPreservesDraftLock() {
        AgentDraftService drafts = mock(AgentDraftService.class);
        ArticleRevisionService revisions = mock(ArticleRevisionService.class);
        BlogRpcProvider provider = new BlogRpcProvider(new AgentServiceAuth(KEY), drafts, revisions);
        DraftRequest bad = DraftRequest.newBuilder().setIdentity(Identity.newBuilder().setUserId(7).setServiceKey("wrong")).build();
        assertEquals(401,provider.readDraft(bad).getError().getStatus());
        verifyNoInteractions(revisions);
        when(drafts.save(eq(7L), any())).thenReturn(Map.of("articleId",Long.toString(BIG)));
        DraftRequest request = DraftRequest.newBuilder().setIdentity(Identity.newBuilder().setUserId(7).setServiceKey(KEY))
                .setArticleId(BIG).setExpectedRevisionId("5").setExpectedLockVersion(0).setBaseDraftHash("base").build();
        assertTrue(provider.saveDraft(request).hasData());
        verify(drafts).save(eq(7L),argThat(d -> d.articleId()==BIG && d.expectedLockVersion()==0 && d.baseDraftHash().equals("base")));
    }
    @Test void conflictsNeverBecomeSuccessOrAutomaticRetry() {
        AgentRpc remote = mock(AgentRpc.class);
        when(remote.serviceQuery(any())).thenReturn(Reply.newBuilder().setError(com.easyjob.rpc.v1.Error.newBuilder().setStatus(409)).build());
        AgentRpcClient client = new AgentRpcClient(remote,new AgentServiceAuth(KEY));
        ResponseStatusException error = assertThrows(ResponseStatusException.class, () -> client.serviceQuery(7L,"feedback_review","","",1,20,""));
        assertEquals(409,error.getStatusCode().value()); verify(remote,times(1)).serviceQuery(any());
    }
    @Test void serviceQueriesPreserveAuthenticatedOwnerAndLargeIds() {
        AgentRpc remote = mock(AgentRpc.class);
        when(remote.serviceQuery(any())).thenAnswer(invocation -> {
            AgentQuery request = invocation.getArgument(0);
            assertEquals(7L, request.getIdentity().getUserId());
            assertEquals(BIG, ((Map<?, ?>) RpcValues.decode(com.easyjob.rpc.v1.Value.newBuilder()
                .setObject(request.getEdit()).build())).get("id"));
            return Reply.newBuilder().setData(RpcValues.encode(Map.of("id", BIG))).build();
        });
        AgentRpcClient client = new AgentRpcClient(remote, new AgentServiceAuth(KEY));
        assertEquals(Map.of("id", BIG), client.edit(7L, "feedback_review", "record", Map.of("id", BIG)));
        verify(remote, times(1)).serviceQuery(any());
    }
}
