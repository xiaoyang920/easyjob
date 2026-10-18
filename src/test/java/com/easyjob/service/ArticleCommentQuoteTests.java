package com.easyjob.service;

import com.easyjob.dto.CommentCreateDTO;
import com.easyjob.dto.CommentQuote;
import com.easyjob.entity.Article;
import com.easyjob.entity.ArticleComment;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.*;
import com.easyjob.service.impl.ArticleCommentServiceImpl;
import com.easyjob.service.impl.NotificationServiceImpl;
import com.easyjob.utils.UserContext;
import org.junit.jupiter.api.*;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ArticleCommentQuoteTests {
    ArticleCommentServiceImpl service; ArticleCommentMapper comments; ArticleMapper articles;
    ArticleCommentAnchorService anchors; ArticleAccessService access;
    Article article; CommentCreateDTO dto;
    @BeforeEach void setup() {
        UserContext.setUserId(7L); service=new ArticleCommentServiceImpl();
        comments=mock(ArticleCommentMapper.class); articles=mock(ArticleMapper.class);
        anchors=mock(ArticleCommentAnchorService.class); access=mock(ArticleAccessService.class);
        var users=mock(UserMapper.class); var user=new User(); user.setUserId(7L); user.setNickName("Reader");
        when(users.selectById(7L)).thenReturn(user);
        ReflectionTestUtils.setField(service,"articleCommentMapper",comments);
        ReflectionTestUtils.setField(service,"articleMapper",articles);
        ReflectionTestUtils.setField(service,"anchors",anchors);
        ReflectionTestUtils.setField(service,"access",access);
        ReflectionTestUtils.setField(service,"userMapper",users);
        ReflectionTestUtils.setField(service,"userActionMapper",mock(UserActionMapper.class));
        ReflectionTestUtils.setField(service,"notificationService",mock(NotificationServiceImpl.class));
        article=new Article(); article.setArticleId(42L); article.setUserId(99L); article.setStatus(1); article.setDeleted(0); article.setRequiredLevel(0); article.setContent("<p>正文</p>");
        when(anchors.lockArticle(42L)).thenReturn(article); when(articles.selectById(42L)).thenReturn(article);
        when(access.canRead(7L,99L,0)).thenReturn(true);
        dto=new CommentCreateDTO(); dto.setArticleId(42L); dto.setArticleUserId(123L); dto.setContent("评论内容");
        doAnswer(invocation->{ ((ArticleComment)invocation.getArgument(0)).setCommentId(101L); return 1; }).when(comments).insert(any(ArticleComment.class));
    }
    @AfterEach void clear() { UserContext.clear(); }
    @Test void quoteAndCommentShareCreationAndAuthorComesFromServer() {
        var quote=new CommentQuote(); quote.setExact("正文"); dto.setQuote(quote);
        when(anchors.validate(quote,article.getContent())).thenReturn(quote);
        var result=service.create(dto);
        assertSame(quote,result.getQuote()); assertEquals("101",result.getCommentId());
        verify(anchors).save(101L,quote);
        verify(comments).insert(argThat((ArticleComment c)->c.getArticleUserId().equals(99L) && c.getStatus()==0));
    }
    @Test void invalidQuoteDoesNotInsertCommentOrIncrementCounts() {
        var quote=new CommentQuote(); dto.setQuote(quote);
        when(anchors.validate(quote,article.getContent())).thenThrow(new BusinessException(409,"已更新"));
        assertThrows(BusinessException.class,()->service.create(dto));
        verifyNoInteractions(comments); verify(articles,never()).changeCommentCount(any(),anyInt());
    }
    @Test void unreadableArticleCannotLeakQuotesOrReceiveComments() {
        when(access.canRead(7L,99L,0)).thenReturn(false);
        assertThrows(BusinessException.class,()->service.create(dto));
        assertThrows(BusinessException.class,()->service.getQuoteComments(42L,1,20));
        verify(anchors,never()).page(any(),anyInt(),anyInt()); verifyNoInteractions(comments);
    }
    @Test void replyCannotCrossArticlesOrAddANewAnchor() {
        dto.setParentId(5L); var parent=new ArticleComment(); parent.setArticleId(43L); parent.setStatus(0);
        when(comments.selectById(5L)).thenReturn(parent);
        assertThrows(BusinessException.class,()->service.create(dto));
        dto.setQuote(new CommentQuote()); assertThrows(BusinessException.class,()->service.create(dto));
        verify(comments,never()).insert(any(ArticleComment.class));
    }
    @Test void deletingSomeoneElsesCommentIsDenied() {
        var comment=new ArticleComment(); comment.setUserId(8L); when(comments.selectById(101L)).thenReturn(comment);
        assertThrows(BusinessException.class,()->service.removeComment(101L));
        verify(comments,never()).deleteById(anyLong());
    }
    @Test void unpublishedArticleIsNotCommentable() {
        article.setStatus(0); assertThrows(BusinessException.class,()->service.create(dto)); verifyNoInteractions(comments);
    }
    @Test void markerAndSelectedThreadReadsHonorLiveReadPermission() {
        when(access.canRead(7L,99L,0)).thenReturn(false);
        assertThrows(BusinessException.class,()->service.getQuoteMarkers(42L,0L,200));
        assertThrows(BusinessException.class,()->service.getSelectedQuoteComments(42L,1,20,List.of(101L)));
        verify(anchors,never()).markers(any(),any(),anyInt());
        verify(anchors,never()).selectedPage(any(),anyInt(),anyInt(),anyList());
    }
    @Test void markerCursorAndSelectedIdsAreBoundedBeforeQuerying() {
        assertThrows(BusinessException.class,()->service.getQuoteMarkers(42L,-1L,200));
        assertThrows(BusinessException.class,()->service.getSelectedQuoteComments(42L,1,20,List.of()));
        assertThrows(BusinessException.class,()->service.getSelectedQuoteComments(42L,1,20,Collections.nCopies(51,101L)));
        service.getQuoteMarkers(42L,0L,10000);
        verify(anchors).markers(42L,0L,200);
    }
}
