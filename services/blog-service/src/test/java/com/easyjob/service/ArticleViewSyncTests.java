package com.easyjob.service;

import com.easyjob.component.ArticleViewSync;
import com.easyjob.component.EsComponent;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.ArticleViewSyncMapper;
import org.springframework.transaction.PlatformTransactionManager;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleViewSyncTests {
    ArticleViewSync.Job job=new ArticleViewSync.Job(42L,9,2,"lease-a");
    ArticleViewSyncMapper store=mock(ArticleViewSyncMapper.class); EsComponent es=mock(EsComponent.class);
    ArticleViewSync sync=spy(new ArticleViewSync(store,es,mock(PlatformTransactionManager.class)));
    void published() {
        doReturn(job).when(sync).claim();
        when(store.findArticleVisibility(eq(42L))).thenReturn(List.of(Map.of("status",1,"deleted",0)));
    }
    @Test void failedEsUpdateRetainsDurableJobAndBacksOff() {
        published(); when(es.syncViewCount("42",9)).thenReturn(false);
        assertTrue(sync.syncOnce());
        verify(sync).retry(job,"es_unavailable_or_document_missing");
        verify(sync,never()).complete(any());
        assertEquals(2,ArticleViewSync.retrySeconds(0));
        assertEquals(300,ArticleViewSync.retrySeconds(30));
    }
    @Test void acknowledgedOlderCountReleasesLeaseWithoutRemovingANewerTarget() {
        published(); when(es.syncViewCount("42",9)).thenReturn(true);
        when(store.completeJob(eq(42L),eq("lease-a"),eq(9))).thenReturn(0);
        sync.syncOnce();
        verify(store).completeJob(eq(42L),eq("lease-a"),eq(9));
        verify(store).releaseNewerTarget(eq(42L),eq("lease-a"));
        verify(sync,never()).retry(any(),any());
    }
    @Test void deletedArticleIsNotResurrectedInSearchAndStaleWorkersAreFenced() {
        doReturn(job).when(sync).claim();
        when(store.findArticleVisibility(eq(42L))).thenReturn(List.of(Map.of("status",1,"deleted",1)));
        sync.syncOnce(); verifyNoInteractions(es);
        verify(store).completeJob(eq(42L),eq("lease-a"),eq(9));
    }
    @Test void thrownTransportErrorIsRetriedAndAnEmptyQueueDoesNoWork() {
        published(); when(es.syncViewCount("42",9)).thenThrow(new IllegalStateException());
        sync.syncOnce(); verify(sync).retry(job,"IllegalStateException");
        doReturn(null).when(sync).claim(); assertFalse(sync.syncOnce());
    }
}
