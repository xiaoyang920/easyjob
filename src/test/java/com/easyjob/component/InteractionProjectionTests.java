package com.easyjob.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.UpdateByQueryRequest;
import co.elastic.clients.elasticsearch.core.UpdateByQueryResponse;
import co.elastic.clients.elasticsearch.core.UpdateRequest;
import co.elastic.clients.util.ObjectBuilder;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.dto.ArticleEsDTO;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings({"unchecked", "rawtypes"})
class InteractionProjectionTests {
    @Test void articleUpdateAssignsBothCountsAndDoesNotCreatePartialDocument() throws Exception {
        var client = mock(ElasticsearchClient.class);
        var text = new EsComponent(); ReflectionTestUtils.setField(text, "client", client);
        when(client.update(any(Function.class), eq(ArticleEsDTO.class))).thenAnswer(call -> {
            Function<UpdateRequest.Builder<ArticleEsDTO, ArticleEsDTO>, ObjectBuilder<UpdateRequest<ArticleEsDTO, ArticleEsDTO>>> build = call.getArgument(0);
            var request = build.apply(new UpdateRequest.Builder<>()).build();
            assertEquals("article", request.index()); assertEquals("42", request.id());
            assertEquals(2, request.script().params().get("likes").to(Integer.class));
            assertEquals(0, request.script().params().get("collects").to(Integer.class));
            assertFalse(request.script().source().contains("+="));
            assertNull(request.upsert()); assertNotEquals(Boolean.TRUE, request.scriptedUpsert());
            return null;
        });
        text.syncInteractionCounts("42", 2, 0);
        verify(client, never()).index(any(Function.class));
    }

    @Test void articleTransportFailureIsNotSwallowed() throws Exception {
        var client = mock(ElasticsearchClient.class);
        var text = new EsComponent(); ReflectionTestUtils.setField(text, "client", client);
        when(client.update(any(Function.class), eq(ArticleEsDTO.class))).thenThrow(new IOException("offline"));
        assertThrows(BusinessException.class, () -> text.syncInteractionCounts("42", 2, 0));
    }

    @Test void vectorUpdateTargetsOneArticleAndAssignsAbsoluteCounts() throws Exception {
        var client = mock(ElasticsearchClient.class);
        var store = new EsVectorStore(); ReflectionTestUtils.setField(store, "esClient", client);
        when(client.updateByQuery(any(Function.class))).thenAnswer(call -> {
            Function<UpdateByQueryRequest.Builder, ObjectBuilder<UpdateByQueryRequest>> build = call.getArgument(0);
            var request = build.apply(new UpdateByQueryRequest.Builder()).build();
            assertEquals("article_id", request.query().term().field());
            assertEquals("42", request.query().term().value().stringValue());
            assertEquals(2, request.script().params().get("likes").to(Integer.class));
            assertEquals(0, request.script().params().get("collects").to(Integer.class));
            assertFalse(request.script().source().contains("+="));
            return UpdateByQueryResponse.of(b -> b.timedOut(false).versionConflicts(0L));
        });
        store.syncInteractionCounts("42", 2, 0);
        verify(client, never()).bulk(any(Function.class));
    }

    @Test void partialVectorFailureAndTimeoutBothReachOutboxRetry() throws Exception {
        var client = mock(ElasticsearchClient.class);
        var store = new EsVectorStore(); ReflectionTestUtils.setField(store, "esClient", client);
        when(client.updateByQuery(any(Function.class))).thenReturn(
                UpdateByQueryResponse.of(b -> b.timedOut(true)),
                UpdateByQueryResponse.of(b -> b.versionConflicts(1L)),
                UpdateByQueryResponse.of(b -> b.failures(f -> f.index("article_vectors").type("_doc").id("42:0").status(500)
                        .cause(c -> c.type("test_failure").reason("one chunk failed")))));
        for (int i = 0; i < 3; i++) assertThrows(BusinessException.class, () -> store.syncInteractionCounts("42", 2, 0));
    }
}
