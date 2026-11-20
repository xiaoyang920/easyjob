package com.easyjob.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserTagPreferenceMapper;
import com.easyjob.service.impl.RecommendServiceImpl;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.*;
import static org.mockito.Mockito.*;

class RecommendationTests {
    @Test void forwardsOwnedTopicsLevelAndFilterWhileRetainingBehaviorSignals() {
        ArticleMapper mapper=mock(ArticleMapper.class); UserTagPreferenceMapper tags=mock(UserTagPreferenceMapper.class);
        ArticlePreferenceService profile=mock(ArticlePreferenceService.class); ArticleAccessService access=mock(ArticleAccessService.class);
        RecommendServiceImpl service=new RecommendServiceImpl();
        ReflectionTestUtils.setField(service,"articleMapper",mapper);
        ReflectionTestUtils.setField(service,"userTagPreferenceMapper",tags);
        ReflectionTestUtils.setField(service,"profile",profile);
        ReflectionTestUtils.setField(service,"access",access);
        when(tags.selectTopTagIds(7L,8)).thenReturn(List.of(12L));
        when(profile.topics(7L)).thenReturn(List.of("Redis"));
        when(access.reader(7L)).thenReturn(new ArticleAccessService.Reader(2,false));
        when(mapper.listRecommendedArticles(any(),any(),any(),any(),any(),any(),any(),anyInt(),anyBoolean(),anyBoolean())).thenReturn(new Page<>());
        service.recommendPage(7L,1,12,3L,List.of(12L,12L,-1L),true);
        verify(mapper).listRecommendedArticles(any(),eq(7L),eq(List.of(12L)),eq(3L),eq(List.of(12L)),eq(List.of("Redis")),
            eq(List.of(ArticlePreferenceService.titlePattern("Redis"))),eq(2),eq(false),eq(true));
    }
}
