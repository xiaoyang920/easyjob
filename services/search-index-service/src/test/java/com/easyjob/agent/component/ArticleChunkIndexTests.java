package com.easyjob.agent.component;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import com.easyjob.agent.service.ArticleEmbeddingService;
import com.easyjob.dto.ArticleVectorMessage;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.ArticleEsDTO;
import com.easyjob.dto.ArticleIndexSnapshot;
import com.easyjob.index.BlogIndexClient;
import com.easyjob.index.ArticleTextIndex;
import com.easyjob.index.IndexingException;
import com.easyjob.listener.ArticleVectorListener;
import org.junit.jupiter.api.Test;
import com.easyjob.component.ArticleIndexLock;
import com.easyjob.mapper.ArticleIndexLockMapper;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.Collections;
import java.util.List;
import java.util.function.Function;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.entity.DocumentChunk;
import org.mockito.InOrder;

@SuppressWarnings({"unchecked", "rawtypes"})
class ArticleChunkIndexTests {
    private ArticleIndexSnapshot article(String content) {
        ArticleEsDTO article = new ArticleEsDTO();
        article.setArticleId(42L); article.setUserId(7L); article.setTitle("RAG"); article.setContent(content);
        article.setStatus(1);
        return new ArticleIndexSnapshot(article, 0, List.of());
    }
    private ArticleVectorMessage message() {
        ArticleVectorMessage message = new ArticleVectorMessage(); message.setArticleId(42L); return message;
    }
    private record Fixture(ArticleVectorListener listener, BlogIndexClient blog, EsVectorStore store,
                           SqlSession connection, ArticleIndexLockMapper release, ArticleTextIndex text) {}
    private Fixture fixture(boolean acquired) throws Exception {
        BlogIndexClient blog = mock(BlogIndexClient.class);
        EsVectorStore store = mock(EsVectorStore.class);
        SqlSessionFactory sessions=mock(SqlSessionFactory.class);
        SqlSession connection=mock(SqlSession.class);
        ArticleIndexLockMapper release=mock(ArticleIndexLockMapper.class);
        when(sessions.openSession(true)).thenReturn(connection);
        when(connection.getMapper(ArticleIndexLockMapper.class)).thenReturn(release);
        when(release.acquire("easyjob_rag_42")).thenReturn(acquired?1:0);
        when(release.release("easyjob_rag_42")).thenReturn(1);
        ArticleTextIndex text = mock(ArticleTextIndex.class);
        ArticleVectorListener listener = new ArticleVectorListener(blog, text, new DocumentChunkService(),
                store, new ArticleIndexLock(sessions));
        return new Fixture(listener, blog, store, connection, release, text);
    }

    @Test void delayedDeleteCannotRemoveRepublishedArticle() throws Exception {
        Fixture f = fixture(true);
        when(f.blog.snapshot(42L)).thenReturn(article("<p>new public content</p>"));
        f.listener.handleVectorDelete(message());
        verify(f.store).saveChunks(anyList());
        verify(f.store).retainChunks(eq("42"), anyList());
        verify(f.store, never()).deleteByArticleId(anyString());
        verify(f.release).release("easyjob_rag_42");
    }
    @Test void completedDeliveryDoesNotRepeatEmbedding() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        ArticleVectorMessage message = message(); message.setIndexJobId("job");
        when(outbox.completed("job", 42L)).thenReturn(true);
        f.listener.handleVectorMessage(message);
        verifyNoInteractions(f.store);
        verify(f.blog, never()).snapshot(anyLong());
    }
    @Test void failedIndexCannotCompleteDelivery() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        when(f.blog.snapshot(42L)).thenReturn(article("<p>before</p>"), article("<p>after</p>"));
        ArticleVectorMessage message = message(); message.setIndexJobId("job");
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(message));
        verify(outbox, never()).complete(anyString(), anyLong());
    }
    @Test void embeddingFailureCannotCompleteOutboxOrRemovePreviousChunks() throws Exception {
        Fixture f = fixture(true);BlogIndexClient outbox = f.blog;
        when(f.blog.snapshot(42L)).thenReturn(article("<p>current</p>"));
        doThrow(new IndexingException("batch failed")).when(f.store).saveChunks(anyList());
        ArticleVectorMessage message=message();message.setIndexJobId("job");
        assertThrows(IndexingException.class,()->f.listener.handleVectorMessage(message));
        verify(outbox,never()).complete(anyString(),anyLong());
        verify(f.store,never()).retainChunks(anyString(),anyList());
        verifyNoInteractions(f.text);verify(f.release).release("easyjob_rag_42");
    }
    @Test void successfulIndexCompletesDeliveryAfterRetainingChunks() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        when(f.blog.snapshot(42L)).thenReturn(article("<p>current</p>"));
        ArticleVectorMessage message = message(); message.setIndexJobId("job");
        f.listener.handleVectorMessage(message);
        InOrder order = inOrder(f.store, f.text, outbox);
        order.verify(f.store).saveChunks(anyList());
        order.verify(f.store).retainChunks(eq("42"), anyList());
        order.verify(f.text).saveDoc(any(ArticleEsDTO.class));
        order.verify(outbox).complete("job", 42L);
    }
    @Test void fullTextFailureDoesNotAcknowledgeOutboxAndCanRetry() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        when(f.blog.snapshot(42L)).thenReturn(article("<p>current</p>"));
        doThrow(new IndexingException("ES offline")).doNothing().when(f.text).saveDoc(any(ArticleEsDTO.class));
        ArticleVectorMessage message = message(); message.setIndexJobId("job");
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(message));
        verify(outbox, never()).complete(anyString(), anyLong());
        f.listener.handleVectorMessage(message);
        verify(outbox).complete("job", 42L);
        verify(f.text, times(2)).saveDoc(any(ArticleEsDTO.class));
    }
    @Test void concurrentArticleEditDoesNotRemovePreviousCompleteIndex() throws Exception {
        Fixture f = fixture(true);
        when(f.blog.snapshot(42L)).thenReturn(article("<p>before</p>"), article("<p>after</p>"));
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(message()));
        verify(f.store).saveChunks(anyList());
        verify(f.store, never()).retainChunks(anyString(), anyList());
        verify(f.release).release("easyjob_rag_42");
    }
    @Test void unavailableLockDoesNotStartEmbeddingOrIndexing() throws Exception {
        Fixture f = fixture(false);
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(message()));
        verifyNoInteractions(f.store, f.blog);
    }
    @Test void unpublishedArticleOnlyRemovesChunks() throws Exception {
        Fixture f = fixture(true);
        when(f.blog.snapshot(42L)).thenReturn(new ArticleIndexSnapshot(null, 0, List.of()));
        f.listener.handleVectorMessage(message());
        verify(f.store).deleteByArticleId("42");
        verify(f.text).deleteDoc(42L);
        verify(f.store, never()).saveChunks(anyList());
    }

    @Test void readingLevelRestrictedContentIsNotEmbedded() throws Exception {
        Fixture f = fixture(true);
        ArticleEsDTO document = article("<p>Restricted content</p>").document();
        when(f.blog.snapshot(42L)).thenReturn(new ArticleIndexSnapshot(document, 2, List.of()));
        f.listener.handleVectorMessage(message());
        verify(f.store).deleteByArticleId("42");
        verify(f.store, never()).saveChunks(anyList());
        verify(f.text).saveDoc(document);
    }
    @Test void emptyEditorHtmlRemovesStaleChunksWithoutEmbedding() throws Exception {
        Fixture f = fixture(true);
        when(f.blog.snapshot(42L)).thenReturn(article("<p><br></p>"));
        f.listener.handleVectorMessage(message());
        verify(f.store).deleteByArticleId("42");
        verify(f.store, never()).saveChunks(anyList());
        verify(f.store, never()).retainChunks(anyString(), anyList());
        verify(f.release).release("easyjob_rag_42");
    }
    @Test void emptyHtmlChangedDuringIndexingCannotDeleteNewerChunks() throws Exception {
        Fixture f = fixture(true);
        when(f.blog.snapshot(42L)).thenReturn(article("<p><br></p>"), article("<p>new body</p>"));
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(message()));
        verifyNoInteractions(f.store);
        verify(f.release).release("easyjob_rag_42");
    }
    @Test void partialBulkFailureIsPropagatedToRabbitRetry() throws Exception {
        EsVectorStore store = new EsVectorStore();
        ElasticsearchClient client = mock(ElasticsearchClient.class);
        ArticleEmbeddingService embedding = mock(ArticleEmbeddingService.class);
        when(embedding.embed(anyList())).thenReturn(List.of(Collections.nCopies(2048, 0.1)));
        when(client.bulk(any(Function.class))).thenReturn(BulkResponse.of(b -> b.errors(true).took(1).items(List.of())));
        ReflectionTestUtils.setField(store, "esClient", client);
        ReflectionTestUtils.setField(store, "articleEmbeddingService", embedding);
        List<DocumentChunk> chunks = new DocumentChunkService().chunk("42", "RAG", "<p>text</p>", 7L, List.of());
        assertThrows(IndexingException.class, () -> store.saveChunks(chunks));
        verify(client).bulk(any(Function.class));
    }

    private ArticleVectorMessage countMessage(String job) {
        ArticleVectorMessage message = message(); message.setAction(RabbitMqConstants.ACTION_COUNTS); message.setIndexJobId(job);
        return message;
    }

    @Test void countJobsReadLatestAbsoluteValuesWithoutReadingBodyOrEmbedding() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        ArticleIndexSnapshot.Counts current = new ArticleIndexSnapshot.Counts(true, 8, 2);
        when(f.blog.counts(42L)).thenReturn(current);
        f.listener.handleVectorMessage(countMessage("job"));
        InOrder order = inOrder(f.blog, f.text, f.store);
        order.verify(f.blog).counts(42L);
        order.verify(f.text).syncInteractionCounts("42", 8, 2);
        order.verify(f.store).syncInteractionCounts("42", 8, 2);
        order.verify(outbox).complete("job", 42L);
        verify(f.blog, never()).snapshot(anyLong());
        verify(f.store, never()).saveChunks(anyList());
        verify(f.text, never()).saveDoc(any(ArticleEsDTO.class));
        verify(f.release).release("easyjob_rag_42");
    }

    @Test void countFailureIsRetriedWithLatestDatabaseStateIncludingCancellations() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        ArticleIndexSnapshot.Counts before = new ArticleIndexSnapshot.Counts(true, 8, 2);
        ArticleIndexSnapshot.Counts after = new ArticleIndexSnapshot.Counts(true, 7, 1);
        when(f.blog.counts(42L)).thenReturn(before, after);
        doThrow(new IndexingException("partial vector failure")).when(f.store).syncInteractionCounts("42", 8, 2);
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(countMessage("job")));
        verify(outbox, never()).complete(anyString(), anyLong());
        f.listener.handleVectorMessage(countMessage("job"));
        verify(f.text).syncInteractionCounts("42", 7, 1);
        verify(f.store).syncInteractionCounts("42", 7, 1);
        verify(outbox).complete("job", 42L);
        verify(f.release, times(2)).release("easyjob_rag_42");
    }

    @Test void textCountFailureDoesNotCompleteOrStartVectorUpdate() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        when(f.blog.counts(42L)).thenReturn(new ArticleIndexSnapshot.Counts(true, 0, 0));
        doThrow(new IndexingException("ES offline")).when(f.text).syncInteractionCounts("42", 0, 0);
        assertThrows(IndexingException.class, () -> f.listener.handleVectorMessage(countMessage("job")));
        verifyNoInteractions(f.store);
        verify(outbox, never()).complete(anyString(), anyLong());
    }

    @Test void lateCountsCannotCreateDocumentsForRemovedOrPrivateArticles() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        ArticleIndexSnapshot.Counts hidden = new ArticleIndexSnapshot.Counts(false, 0, 0);
        when(f.blog.counts(42L)).thenReturn(hidden);
        f.listener.handleVectorMessage(countMessage("hidden"));
        f.listener.handleVectorMessage(countMessage("removed"));
        verifyNoInteractions(f.store, f.text);
        verify(outbox).complete("hidden", 42L);
        verify(outbox).complete("removed", 42L);
    }

    @Test void duplicateCompletedCountMessageSkipsAllDatabaseAndIndexWork() throws Exception {
        Fixture f = fixture(true); BlogIndexClient outbox = f.blog;
        when(outbox.completed("job", 42L)).thenReturn(true);
        f.listener.handleVectorMessage(countMessage("job"));
        verifyNoInteractions(f.store, f.text);
        verify(f.blog, never()).counts(anyLong());
    }
    @Test void invalidVectorNeverReachesBulkWrite() {
        EsVectorStore store = new EsVectorStore();
        ElasticsearchClient client = mock(ElasticsearchClient.class);
        ArticleEmbeddingService embedding = mock(ArticleEmbeddingService.class);
        when(embedding.embed(anyList())).thenReturn(List.of(List.of(Double.NaN)));
        ReflectionTestUtils.setField(store, "esClient", client);
        ReflectionTestUtils.setField(store, "articleEmbeddingService", embedding);
        List<DocumentChunk> chunks = new DocumentChunkService().chunk("42", "RAG", "<p>text</p>", 7L, List.of());
        assertThrows(IndexingException.class, () -> store.saveChunks(chunks));
        verifyNoInteractions(client);
    }
}
