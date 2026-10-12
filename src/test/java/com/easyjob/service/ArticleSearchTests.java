package com.easyjob.service;

import com.easyjob.component.EsComponent;
import com.easyjob.mapper.ArticleSearchMapper;
import com.easyjob.vo.ArticleSearchVO;
import com.easyjob.vo.PageVO;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleSearchTests {
    @Test void staleSearchHitsAreFilteredAndPublicationMetadataIsReadFresh() {
        var es=mock(EsComponent.class);var store=mock(ArticleSearchMapper.class);
        var current=new ArticleSearchVO();current.setArticleId("42");current.setSummary("stale");
        var hidden=new ArticleSearchVO();hidden.setArticleId("43");
        var page=new PageVO<ArticleSearchVO>(List.of(current,hidden),2L,20L,1L,1L);
        when(es.search(true,"Java",null,1,20)).thenReturn(page);
        when(store.findCurrentArticles(List.of(42L,43L))).thenReturn(List.of(Map.of("article_id",42L,"required_level",2,"summary","fresh")));
        var result=new ArticleSearchService(es,store).search(true,"Java",null,1,20);
        assertEquals(List.of(current),result.getRecords());
        assertEquals("fresh",current.getSummary());assertEquals(2,current.getRequiredLevel());
    }
    @Test void emptyRecallSkipsDatabaseLookup() {
        var es=mock(EsComponent.class);var store=mock(ArticleSearchMapper.class);
        when(es.search(false,"absent",null,1,20)).thenReturn(new PageVO<>(List.of(),0L,20L,1L,0L));
        assertTrue(new ArticleSearchService(es,store).search(false,"absent",null,1,20).getRecords().isEmpty());
        verifyNoInteractions(store);
    }
}
