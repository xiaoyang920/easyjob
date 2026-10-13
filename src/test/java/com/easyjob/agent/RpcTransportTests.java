package com.easyjob.agent;

import com.easyjob.agent.rpc.*;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.rpc.v1.*;
import com.easyjob.service.ArticleRevisionService;
import org.apache.dubbo.common.stream.StreamObserver;
import org.apache.dubbo.rpc.RpcContext;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class RpcTransportTests {
    static final String KEY = "rpc-test-service-key-at-least-32-bytes";
    static final long BIG = 9007199254740993L;
    @Test void valuesPreserveLongIdsAndEmptyCollections() {
        var value = new LinkedHashMap<String,java.lang.Object>();
        value.put("id",BIG); value.put("null",null); value.put("bool",true);
        value.put("items",List.of()); value.put("nested",Map.of("text","中文"));
        assertEquals(value, RpcValues.decode(RpcValues.encode(value)));
        assertThrows(IllegalArgumentException.class, () -> RpcValues.encode(Double.NaN));
    }
    @Test void providerAuthenticatesBeforeBusinessServiceAndPreservesDraftLock() {
        var drafts = mock(AgentDraftService.class);
        var revisions = mock(ArticleRevisionService.class);
        var provider = new BlogRpcProvider(new AgentServiceAuth(KEY), drafts, revisions);
        var bad = DraftRequest.newBuilder().setIdentity(Identity.newBuilder().setUserId(7).setServiceKey("wrong")).build();
        assertEquals(401,provider.readDraft(bad).getError().getStatus());
        verifyNoInteractions(revisions);
        when(drafts.save(eq(7L), any())).thenReturn(Map.of("articleId",Long.toString(BIG)));
        var request = DraftRequest.newBuilder().setIdentity(Identity.newBuilder().setUserId(7).setServiceKey(KEY))
                .setArticleId(BIG).setExpectedRevisionId("5").setExpectedLockVersion(0).setBaseDraftHash("base").build();
        assertTrue(provider.saveDraft(request).hasData());
        verify(drafts).save(eq(7L),argThat(d -> d.articleId()==BIG && d.expectedLockVersion()==0 && d.baseDraftHash().equals("base")));
    }
    @Test void conflictsNeverBecomeSuccessOrAutomaticRetry() {
        var remote = mock(AgentRpc.class);
        when(remote.cancel(any())).thenReturn(Reply.newBuilder().setError(com.easyjob.rpc.v1.Error.newBuilder().setStatus(409)).build());
        var client = new AgentRpcClient(remote,new AgentServiceAuth(KEY));
        var error = assertThrows(ResponseStatusException.class, () -> client.post("/chat/42/cancel?user_id=7",7L,null));
        assertEquals(409,error.getStatusCode().value()); verify(remote,times(1)).cancel(any());
    }
    @Test void streamKeepsDataAndSubscriberCancellationCancelsTransport() {
        var remote = mock(AgentRpc.class);
        var captured = new org.apache.dubbo.rpc.CancellationContext[1];
        doAnswer(invocation -> {
            captured[0]=RpcContext.getCancellationContext();
            StreamObserver<Frame> observer=invocation.getArgument(1);
            observer.onNext(Frame.newBuilder().setData("__REPLY__:正文").build());
            return null;
        }).when(remote).runEvents(any(),any());
        var client = new AgentRpcClient(remote,new AgentServiceAuth(KEY));
        assertEquals(List.of("__REPLY__:正文"),client.events(7L,"12345678-1234-1234-1234-123456789abc",BIG).take(1).collectList().block());
        assertTrue(captured[0].isCancelled());
        verify(remote,never()).cancel(any());
    }
}
