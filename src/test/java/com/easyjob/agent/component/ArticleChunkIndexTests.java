package com.easyjob.agent.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import com.easyjob.agent.service.ZhipuEmbeddingService;
import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.entity.Article;
import com.easyjob.exception.BusinessException;
import com.easyjob.listener.ArticleVectorListener;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Collections;
import java.util.List;
import java.util.function.Function;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings({"unchecked", "rawtypes"})
class ArticleChunkIndexTests {
    private Article article(String content) {
        Article article = new Article();
        article.setArticleId(42L); article.setUserId(7L); article.setTitle("RAG"); article.setContent(content);
        article.setStatus(1); article.setDeleted(0);
        return article;
    }
    private ArticleVectorMessage message() {
        ArticleVectorMessage message = new ArticleVectorMessage(); message.setArticleId(42L); return message;
    }
    private record Fixture(ArticleVectorListener listener, ArticleMapper mapper, EsVectorStore store,
                           Connection connection, PreparedStatement release, com.easyjob.component.EsComponent text) {}
    private Fixture fixture(boolean acquired) throws Exception {
        var mapper = mock(ArticleMapper.class);
        var tags = mock(ArticleTagMapper.class);
        var store = mock(EsVectorStore.class);
        var jdbc = mock(JdbcTemplate.class);
        var connection = mock(Connection.class);
        var lock = mock(PreparedStatement.class); var release = mock(PreparedStatement.class);
        var result = mock(ResultSet.class);
        when(connection.prepareStatement("SELECT GET_LOCK(?, 10)")).thenReturn(lock);
        when(connection.prepareStatement("SELECT RELEASE_LOCK(?)")).thenReturn(release);
        when(lock.executeQuery()).thenReturn(result); when(result.next()).thenReturn(true);
        when(result.getInt(1)).thenReturn(acquired ? 1 : 0);
        when(jdbc.execute(any(ConnectionCallback.class))).thenAnswer(call -> ((ConnectionCallback<?>) call.getArgument(0)).doInConnection(connection));
        when(tags.getTagsByArticleId(42L)).thenReturn(List.of());
        var listener = new ArticleVectorListener();
        ReflectionTestUtils.setField(listener, "articleMapper", mapper);
        ReflectionTestUtils.setField(listener, "articleTagMapper", tags);
        ReflectionTestUtils.setField(listener, "esVectorStore", store);
        ReflectionTestUtils.setField(listener, "documentChunkService", new DocumentChunkService());
        ReflectionTestUtils.setField(listener, "jdbc", jdbc);
        var text = mock(com.easyjob.component.EsComponent.class);
        ReflectionTestUtils.setField(listener, "esComponent", text);
        return new Fixture(listener, mapper, store, connection, release, text);
    }

    @Test void delayedDeleteCannotRemoveRepublishedArticle() throws Exception {
        var f = fixture(true);
        when(f.mapper.selectById(42L)).thenReturn(article("<p>new public content</p>"));
        f.listener.handleVectorDelete(message());
        verify(f.store).saveChunks(anyList());
        verify(f.store).retainChunks(eq("42"), anyList());
        verify(f.store, never()).deleteByArticleId(anyString());
        verify(f.release).execute();
    }
    @Test void completedDeliveryDoesNotRepeatEmbedding() throws Exception {
        var f = fixture(true); var outbox = mock(ArticleIndexOutbox.class);
        ReflectionTestUtils.setField(f.listener, "indexOutbox", outbox);
        var message = message(); message.setIndexJobId("job");
        when(outbox.completed("job", 42L)).thenReturn(true);
        f.listener.handleVectorMessage(message);
        verifyNoInteractions(f.store, f.mapper);
    }
    @Test void failedIndexCannotCompleteDelivery() throws Exception {
        var f = fixture(true); var outbox = mock(ArticleIndexOutbox.class);
        ReflectionTestUtils.setField(f.listener, "indexOutbox", outbox);
        when(f.mapper.selectById(42L)).thenReturn(article("<p>before</p>"), article("<p>after</p>"));
        var message = message(); message.setIndexJobId("job");
        assertThrows(BusinessException.class, () -> f.listener.handleVectorMessage(message));
        verify(outbox, never()).complete(anyString(), anyLong());
    }
    @Test void successfulIndexCompletesDeliveryAfterRetainingChunks() throws Exception {
        var f = fixture(true); var outbox = mock(ArticleIndexOutbox.class);
        ReflectionTestUtils.setField(f.listener, "indexOutbox", outbox);
        when(f.mapper.selectById(42L)).thenReturn(article("<p>current</p>"));
        var message = message(); message.setIndexJobId("job");
        f.listener.handleVectorMessage(message);
        var order = inOrder(f.store, f.text, outbox);
        order.verify(f.store).saveChunks(anyList());
        order.verify(f.store).retainChunks(eq("42"), anyList());
        order.verify(f.text).saveDoc(any(Article.class));
        order.verify(outbox).complete("job", 42L);
    }
    @Test void fullTextFailureDoesNotAcknowledgeOutboxAndCanRetry() throws Exception {
        var f = fixture(true); var outbox = mock(ArticleIndexOutbox.class);
        ReflectionTestUtils.setField(f.listener, "indexOutbox", outbox);
        when(f.mapper.selectById(42L)).thenReturn(article("<p>current</p>"));
        doThrow(new BusinessException("ES offline")).doNothing().when(f.text).saveDoc(any(Article.class));
        var message = message(); message.setIndexJobId("job");
        assertThrows(BusinessException.class, () -> f.listener.handleVectorMessage(message));
        verify(outbox, never()).complete(anyString(), anyLong());
        f.listener.handleVectorMessage(message);
        verify(outbox).complete("job", 42L);
        verify(f.text, times(2)).saveDoc(any(Article.class));
    }
    @Test void concurrentArticleEditDoesNotRemovePreviousCompleteIndex() throws Exception {
        var f = fixture(true);
        when(f.mapper.selectById(42L)).thenReturn(article("<p>before</p>"), article("<p>after</p>"));
        assertThrows(BusinessException.class, () -> f.listener.handleVectorMessage(message()));
        verify(f.store).saveChunks(anyList());
        verify(f.store, never()).retainChunks(anyString(), anyList());
        verify(f.release).execute();
    }
    @Test void unavailableLockDoesNotStartEmbeddingOrIndexing() throws Exception {
        var f = fixture(false);
        assertThrows(BusinessException.class, () -> f.listener.handleVectorMessage(message()));
        verifyNoInteractions(f.store, f.mapper);
    }
    @Test void unpublishedArticleOnlyRemovesChunks() throws Exception {
        var f = fixture(true);
        var article = article("<p>private</p>"); article.setStatus(0);
        when(f.mapper.selectById(42L)).thenReturn(article);
        f.listener.handleVectorMessage(message());
        verify(f.store).deleteByArticleId("42");
        verify(f.store, never()).saveChunks(anyList());
    }
    @Test void emptyEditorHtmlRemovesStaleChunksWithoutEmbedding() throws Exception {
        var f = fixture(true);
        when(f.mapper.selectById(42L)).thenReturn(article("<p><br></p>"));
        f.listener.handleVectorMessage(message());
        verify(f.store).deleteByArticleId("42");
        verify(f.store, never()).saveChunks(anyList());
        verify(f.store, never()).retainChunks(anyString(), anyList());
        verify(f.release).execute();
    }
    @Test void emptyHtmlChangedDuringIndexingCannotDeleteNewerChunks() throws Exception {
        var f = fixture(true);
        when(f.mapper.selectById(42L)).thenReturn(article("<p><br></p>"), article("<p>new body</p>"));
        assertThrows(BusinessException.class, () -> f.listener.handleVectorMessage(message()));
        verifyNoInteractions(f.store);
        verify(f.release).execute();
    }
    @Test void partialBulkFailureIsPropagatedToRabbitRetry() throws Exception {
        var store = new EsVectorStore();
        var client = mock(ElasticsearchClient.class);
        var embedding = mock(ZhipuEmbeddingService.class);
        when(embedding.embedBatch(anyList())).thenReturn(List.of(Collections.nCopies(2048, 0.1)));
        when(client.bulk(any(Function.class))).thenReturn(BulkResponse.of(b -> b.errors(true).took(1).items(List.of())));
        ReflectionTestUtils.setField(store, "esClient", client);
        ReflectionTestUtils.setField(store, "embeddingService", embedding);
        var chunks = new DocumentChunkService().chunk("42", "RAG", "<p>text</p>", 7L, List.of());
        assertThrows(BusinessException.class, () -> store.saveChunks(chunks));
        verify(client).bulk(any(Function.class));
    }
    @Test void invalidVectorNeverReachesBulkWrite() {
        var store = new EsVectorStore();
        var client = mock(ElasticsearchClient.class);
        var embedding = mock(ZhipuEmbeddingService.class);
        when(embedding.embedBatch(anyList())).thenReturn(List.of(List.of(Double.NaN)));
        ReflectionTestUtils.setField(store, "esClient", client);
        ReflectionTestUtils.setField(store, "embeddingService", embedding);
        var chunks = new DocumentChunkService().chunk("42", "RAG", "<p>text</p>", 7L, List.of());
        assertThrows(BusinessException.class, () -> store.saveChunks(chunks));
        verifyNoInteractions(client);
    }
}
