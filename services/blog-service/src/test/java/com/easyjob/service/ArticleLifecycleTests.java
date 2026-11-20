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
        when(revisions.create(anyLong(),anyLong(),any())).thenAnswer(call->java.util.Map.of("articleId",call.getArgument(1).toString()));
        ReflectionTestUtils.setField(service, "articleMapper", mapper);
        ReflectionTestUtils.setField(service, "userMapper", users);
        ReflectionTestUtils.setField(service, "esComponent", es);
        ReflectionTestUtils.setField(service, "redisComponent", redis);
        ReflectionTestUtils.setField(service, "cacheRebuildMutex", new com.easyjob.component.CacheRebuildMutex(
                mock(org.springframework.data.redis.core.StringRedisTemplate.class), 30000, 2000));
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
    @Test void cachedArticleStillReadsFreshCountsAndChecksAccess() {
        UserContext.clear();
        ArticleDetailVO cached = new ArticleDetailVO();
        cached.setArticleId("42"); cached.setTitle("cached title"); cached.setViewCount(1);
        when(redis.getArticleDetail(42L)).thenReturn(cached);
        Article current = new Article();
        current.setStatus(1); current.setDeleted(0); current.setUserId(7L); current.setViewCount(99);
        when(mapper.selectOne(any())).thenReturn(current);
        ArticleDetailVO result = service.getArticleById(42L);
        assertEquals("cached title", result.getTitle()); assertEquals(99, result.getViewCount());
        assertEquals(1, cached.getViewCount());
        verify(mapper, never()).selectArticleAndUser(anyLong());
        verify(redis, never()).saveArticleDetail(anyLong(), any());
        verify((ArticleAccessService) ReflectionTestUtils.getField(service, "articleAccess"))
                .apply(eq(result), isNull(), eq(7L), eq(0));
    }
    @Test void cacheHitCannotExposeAnUnpublishedArticle() {
        when(redis.getArticleDetail(42L)).thenReturn(new ArticleDetailVO());
        Article current = new Article(); current.setStatus(0); current.setDeleted(0);
        when(mapper.selectOne(any())).thenReturn(current);
        assertEquals(404, assertThrows(BusinessException.class, () -> service.getArticleById(42L)).getCode());
        verify(mapper, never()).selectArticleAndUser(anyLong());
    }
    @Test void savingDraftReturnsIdWithoutCountingOrPublishing() {
        assertTrue(service.saveArticle(request(0))>0);
        verify(revisions).create(eq(7L),anyLong(),any(ArticleCreateDTO.class));
        verify(mapper,never()).insert(any(Article.class));
        verifyNoInteractions(users, es, index);
    }
    @Test void creatingSubmissionDoesNotPublishOrCount() {
        service.saveArticle(request(1));
        verify(revisions).create(eq(7L),anyLong(),any(ArticleCreateDTO.class));
        verify(mapper,never()).insert(any(Article.class));
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
        verify(revisions).delete(7L,42L);
    }
    @Test void deletingPublishedArticleDecreasesPublishedCount() {
        existing(1); service.deleteArticle(42L); verify(revisions).delete(7L,42L);verifyNoInteractions(users,index);
    }
    @Test void missingOrForeignArticleCannotMutateTagsOrCounters() {
        doThrow(new BusinessException(404,"不存在")).when(revisions).delete(7L,42L);
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
        verifyNoInteractions(redis);verify(revisions).delete(7L,42L);
    }
}
