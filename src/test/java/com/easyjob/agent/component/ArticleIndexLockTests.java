package com.easyjob.agent.component;

import com.easyjob.component.ArticleIndexLock;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleIndexLockMapper;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleIndexLockTests {
    @Test void releaseUsesTheAcquiringSessionAndRunsBeforeClosingOnFailure() {
        var factory=mock(SqlSessionFactory.class);var session=mock(SqlSession.class);
        var mapper=mock(ArticleIndexLockMapper.class);var work=mock(Runnable.class);
        when(factory.openSession(true)).thenReturn(session);
        when(session.getMapper(ArticleIndexLockMapper.class)).thenReturn(mapper);
        when(mapper.acquire("easyjob_rag_42")).thenReturn(1);
        when(mapper.release("easyjob_rag_42")).thenReturn(1);
        var error=new IllegalStateException("index failed");doThrow(error).when(work).run();
        assertSame(error,assertThrows(IllegalStateException.class,()->new ArticleIndexLock(factory).withLock(42L,work)));
        var order=inOrder(factory,session,mapper,work);
        order.verify(factory).openSession(true);order.verify(session).getMapper(ArticleIndexLockMapper.class);
        order.verify(mapper).acquire("easyjob_rag_42");order.verify(work).run();
        order.verify(mapper).release("easyjob_rag_42");order.verify(session).close();
        verify(factory,times(1)).openSession(anyBoolean());
    }
    @Test void timeoutCannotRunOrReleaseAnotherWorkersLock() {
        var factory=mock(SqlSessionFactory.class);var session=mock(SqlSession.class);
        var mapper=mock(ArticleIndexLockMapper.class);var work=mock(Runnable.class);
        when(factory.openSession(true)).thenReturn(session);
        when(session.getMapper(ArticleIndexLockMapper.class)).thenReturn(mapper);
        when(mapper.acquire(anyString())).thenReturn(0);
        assertThrows(BusinessException.class,()->new ArticleIndexLock(factory).withLock(42L,work));
        verifyNoInteractions(work);verify(mapper,never()).release(anyString());verify(session).close();
    }
}
