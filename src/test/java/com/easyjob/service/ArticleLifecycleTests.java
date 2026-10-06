package com.easyjob.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.EsComponent;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.entity.Article;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.impl.ArticleServiceImpl;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ArticleDetailVO;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.*;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.time.LocalDateTime;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleLifecycleTests {
    ArticleMapper mapper;
    UserMapper users;
    EsComponent es;
    RedisComponent redis;
    ArticleIndexPublisher index;
    ArticleTagService tags;
    ArticleTagMapper tagMapper;
    ArticleServiceImpl service;
    ArticleRevisionService revisions;

    @BeforeAll static void metadata() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), Article.class);
    }
    @BeforeEach void setup() {
        UserContext.setUserId(7L);
        mapper = mock(ArticleMapper.class); users = mock(UserMapper.class);
        es = mock(EsComponent.class); redis = mock(RedisComponent.class);
        index = mock(ArticleIndexPublisher.class); tags = mock(ArticleTagService.class);
        tagMapper = mock(ArticleTagMapper.class); service = new ArticleServiceImpl();
        revisions=mock(ArticleRevisionService.class);ReflectionTestUtils.setField(service,"revisions",revisions);
        ReflectionTestUtils.setField(service, "articleMapper", mapper);
        ReflectionTestUtils.setField(service, "userMapper", users);
        ReflectionTestUtils.setField(service, "esComponent", es);
        ReflectionTestUtils.setField(service, "redisComponent", redis);
        ReflectionTestUtils.setField(service, "articleIndexPublisher", index);
        ReflectionTestUtils.setField(service, "articleTagService", tags);
        ReflectionTestUtils.setField(service, "articleTagMapper", tagMapper);
        ReflectionTestUtils.setField(service, "articleAccess", mock(ArticleAccessService.class));
        when(mapper.update(any(Article.class), any())).thenReturn(1);
        when(mapper.delete(any(Wrapper.class))).thenReturn(1);
        when(mapper.insert(any(Article.class))).thenAnswer(call -> {
            ((Article) call.getArgument(0)).setArticleId(42L); return 1;
        });
    }
    @AfterEach void cleanup() {
        UserContext.clear();
        TransactionSynchronizationManager.clear();
    }
    Article existing(int status) {
        Article article = new Article(); article.setArticleId(42L); article.setUserId(7L);
        article.setStatus(status); article.setDeleted(0); article.setViewCount(18);
        if (status == 1) article.setPublishTime(LocalDateTime.of(2026, 9, 1, 12, 0));
        when(mapper.selectOne(any())).thenAnswer(call -> {
            Wrapper<?> query = call.getArgument(0);
            assertTrue(query.getSqlSegment().contains("user_id"));
            assertTrue(query.getSqlSegment().contains("deleted"));
            return article;
        });
        return article;
    }
    ArticleCreateDTO request(int status) {
        ArticleCreateDTO dto = new ArticleCreateDTO(); dto.setStatus(status);
        dto.setCategoryId("1"); dto.setTitle("Lifecycle regression"); dto.setContent("<p>content</p>");
        return dto;
    }
    @Test void savingDraftReturnsIdWithoutCountingOrPublishing() {
        assertEquals(42L, service.saveArticle(request(0)));
        verifyNoInteractions(users, es, index);
    }
    @Test void creatingSubmissionDoesNotPublishOrCount() {
        service.saveArticle(request(1));
        verify(mapper).insert(argThat((Article a)->a.getStatus()==0 && a.getPublishTime()==null));
        verifyNoInteractions(users,index);
    }
    @Test void unsupportedVisibilityCannotBeSubmitted() {
        assertThrows(BusinessException.class,()->service.updateArticle(42L,request(2)));
        verifyNoInteractions(revisions,users,index);
    }
    @Test void publishedEditsPreservePublicationTimeCountersAndOwnership() {
        existing(1);service.updateArticle(42L,request(1));
        verify(mapper,never()).update(any(Article.class),any());verifyNoInteractions(users,index,tags);
    }
    @Test void submittingChangesDoesNotTouchCounters() {
        service.updateArticle(42L,request(1));
        verifyNoInteractions(users,index);
    }
    @Test void legacyDirectPublishCannotBypassReview() {
        assertThrows(BusinessException.class,()->service.publish(42L));
        verifyNoInteractions(users,index);
    }
    @Test void deletingDraftDoesNotDecreasePublishedCount() {
        existing(0); service.deleteArticle(42L); verifyNoInteractions(users);
        verify(redis).deleteUserSpaceVO(7L);
    }
    @Test void deletingPublishedArticleDecreasesPublishedCount() {
        existing(1); service.deleteArticle(42L); verify(users).changeArticleCount(7L, -1);
    }
    @Test void missingOrForeignArticleCannotMutateTagsOrCounters() {
        assertThrows(BusinessException.class,()->service.deleteArticle(42L));
        verifyNoInteractions(users,tags,index);
    }
    @Test void editableViewCarriesPublicAndRevisionStates() {
        ArticleDetailVO detail=new ArticleDetailVO();detail.setStatus(1);detail.setRevisionState(0);
        when(revisions.editable(7L,42L)).thenReturn(detail);
        assertEquals(1,service.getEditableArticle(42L).getStatus());verifyNoInteractions(redis);
    }
    @Test void moderatedStatusCannotBePublishedOrEditedAsDraft() {
        assertThrows(BusinessException.class,()->service.publish(42L));verifyNoInteractions(users,index);
    }
    @Test void cachesAreInvalidatedOnlyAfterCommit() {
        existing(1);TransactionSynchronizationManager.initSynchronization();TransactionSynchronizationManager.setActualTransactionActive(true);
        service.deleteArticle(42L);verifyNoInteractions(redis);
        TransactionSynchronizationManager.getSynchronizations().forEach(s->s.afterCommit());
        verify(redis).deleteArticleDetail(42L);verify(redis).deleteUserSpaceVO(7L);
    }
}
