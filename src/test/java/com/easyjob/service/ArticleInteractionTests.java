package com.easyjob.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.constants.RabbitMqConstants;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.Article;
import com.easyjob.entity.UserAction;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserActionMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.impl.NotificationServiceImpl;
import com.easyjob.service.impl.UserActionServiceImpl;
import com.easyjob.utils.UserContext;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@SuppressWarnings("unchecked")
class ArticleInteractionTests {
    final ArticleMapper articles = mock(ArticleMapper.class);
    final UserActionMapper actions = mock(UserActionMapper.class);
    final ArticleIndexPublisher publisher = mock(ArticleIndexPublisher.class);
    final NotificationServiceImpl notifications = mock(NotificationServiceImpl.class);
    final UserMapper users = mock(UserMapper.class);
    final UserActionServiceImpl service = new UserActionServiceImpl();
    Article article;

    @BeforeEach void setup() {
        var configuration = new Configuration(); configuration.setMapUnderscoreToCamelCase(true);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, "test"), UserAction.class);
        ReflectionTestUtils.setField(service, "articleMapper", articles);
        ReflectionTestUtils.setField(service, "userActionMapper", actions);
        ReflectionTestUtils.setField(service, "articleIndexPublisher", publisher);
        ReflectionTestUtils.setField(service, "notificationService", notifications);
        ReflectionTestUtils.setField(service, "userMapper", users);
        UserContext.setUserId(9L);
        article = new Article(); article.setArticleId(42L); article.setUserId(7L);
        article.setStatus(1); article.setDeleted(0); article.setTitle("RAG");
        article.setLikeCount(5); article.setCollectCount(3);
        when(articles.lockForInteraction(42L)).thenReturn(article);
        when(actions.insert(any(UserAction.class))).thenReturn(1);
        when(actions.delete(any(Wrapper.class))).thenReturn(1);
    }

    @AfterEach void cleanup() { UserContext.clear(); }

    UserActionService.InteractionResult change(boolean like, Boolean active) {
        return like ? service.like(42L, active) : service.collect(42L, active);
    }

    @ParameterizedTest @ValueSource(booleans = {true, false})
    void activateLocksArticleThenPersistsRelationshipCounterAndOneDelivery(boolean like) {
        var result = change(like, true);
        assertTrue(result.active()); assertEquals(like ? 6 : 4, result.count());
        var order = inOrder(articles, actions, publisher, notifications);
        order.verify(articles).lockForInteraction(42L);
        order.verify(actions).selectOne(argThat(w -> w.getSqlSegment().contains("comment_id")
                && w.getSqlSegment().contains("user_id") && w.getSqlSegment().contains("action_type")));
        order.verify(actions).insert(argThat((UserAction a) -> a.getArticleId()==42L && a.getUserId()==9L
                && a.getCommentId()==0L && a.getArticleUserId()==7L && a.getActionType()==(like?2:3)));
        if (like) order.verify(articles).changeLikeCount(42L, 1);
        else order.verify(articles).changeCollectCount(42L, 1);
        order.verify(publisher).publish(42L, RabbitMqConstants.ACTION_COUNTS, RabbitMqConstants.ROUTING_KEY_UPDATE);
        order.verify(notifications).send(any(NotificationMessage.class));
        verify(articles, never()).selectById(anyLong());
    }

    @ParameterizedTest @ValueSource(booleans = {true, false})
    void repeatedActivationDoesNotToggleOrAddAnotherTaskAndNotification(boolean like) {
        when(actions.selectOne(any(Wrapper.class))).thenReturn(new UserAction());
        assertEquals(new UserActionService.InteractionResult(true, like?5:3), change(like, true));
        verify(actions, never()).insert(any(UserAction.class));
        verify(actions, never()).delete(any(Wrapper.class));
        verify(articles, never()).changeLikeCount(anyLong(), anyInt());
        verify(articles, never()).changeCollectCount(anyLong(), anyInt());
        verifyNoInteractions(publisher, notifications, users);
    }

    @ParameterizedTest @ValueSource(booleans = {true, false})
    void repeatedDeactivationDoesNotWrite(boolean like) {
        assertEquals(new UserActionService.InteractionResult(false, like?5:3), change(like, false));
        verifyNoInteractions(publisher, notifications, users);
        verify(actions, never()).delete(any(Wrapper.class));
    }

    @ParameterizedTest @ValueSource(booleans = {true, false})
    void deactivateRemovesRelationshipAndDecrementsWithoutNotification(boolean like) {
        when(actions.selectOne(any(Wrapper.class))).thenReturn(new UserAction());
        assertEquals(new UserActionService.InteractionResult(false, like?4:2), change(like, false));
        verify(actions).delete(any(Wrapper.class));
        if (like) verify(articles).changeLikeCount(42L, -1);
        else verify(articles).changeCollectCount(42L, -1);
        verify(publisher).publish(42L, RabbitMqConstants.ACTION_COUNTS, RabbitMqConstants.ROUTING_KEY_UPDATE);
        verifyNoInteractions(notifications, users);
    }

    @Test void nullTargetPreservesLegacyToggleClients() {
        service.like(42L); verify(articles).changeLikeCount(42L, 1);
        when(actions.selectOne(any(Wrapper.class))).thenReturn(new UserAction());
        service.collect(42L); verify(articles).changeCollectCount(42L, -1);
    }

    @Test void selfLikeDoesNotNotifyOrLoadUserProfile() {
        article.setUserId(9L); change(true, true); verifyNoInteractions(notifications, users);
    }

    @Test void missingOrNonpublicArticlesCannotBeMutated() {
        for (int status : new int[]{0, 2}) {
            article.setStatus(status); assertThrows(BusinessException.class, () -> change(true, true));
        }
        article.setStatus(1); article.setDeleted(1);
        assertThrows(BusinessException.class, () -> change(false, true));
        when(articles.lockForInteraction(42L)).thenReturn(null);
        assertThrows(BusinessException.class, () -> change(true, true));
        verifyNoInteractions(actions, publisher, notifications);
    }

    @Test void anonymousOrInvalidRequestsDoNotAccessDatabase() {
        UserContext.clear(); assertThrows(BusinessException.class, () -> change(true, true));
        UserContext.setUserId(9L);
        assertThrows(BusinessException.class, () -> service.like(-1L, true));
        assertThrows(BusinessException.class, () -> service.collect(null, true));
        verifyNoInteractions(articles, actions, publisher, notifications);
    }

    @Test void failedInsertCannotChangeCounterOrScheduleDelivery() {
        when(actions.insert(any(UserAction.class))).thenReturn(0);
        assertThrows(BusinessException.class, () -> change(true, true));
        verify(articles, never()).changeLikeCount(anyLong(), anyInt());
        verifyNoInteractions(publisher, notifications);
    }

    @Test void countersNeverGoBelowZero() {
        article.setLikeCount(0); when(actions.selectOne(any(Wrapper.class))).thenReturn(new UserAction());
        assertEquals(0, change(true, false).count());
    }
}
