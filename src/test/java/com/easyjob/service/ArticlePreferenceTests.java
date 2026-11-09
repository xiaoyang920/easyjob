package com.easyjob.service;

import org.junit.jupiter.api.Test;
import com.easyjob.mapper.ArticlePreferenceMapper;
import java.util.*;
import java.util.regex.Pattern;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticlePreferenceTests {
    @Test void readsMergedLegacyTopicsWithoutCachingDeletedPreferences() {
        ArticlePreferenceMapper store=mock(ArticlePreferenceMapper.class); ArticlePreferenceService service=new ArticlePreferenceService(store);
        when(store.findTopics(eq(7L))).thenReturn(
            List.of(Map.of("interests","[\"Redis\",\" Agent \"]","tech_stack","[\"redis\",\"Java\"]")),
            List.of(Map.of("interests","[\"Java\"]","tech_stack","[]")));
        assertEquals(List.of("Redis","Agent","Java"),service.topics(7L));
        assertEquals(List.of("Java"),service.topics(7L));
        assertEquals(List.of(),service.topics(null));
        verify(store,times(2)).findTopics(eq(7L));
    }
    @Test void titlePatternsMatchWordsAndLiteralSpecialCharacters() {
        Pattern java=Pattern.compile(ArticlePreferenceService.titlePattern("Java"),Pattern.CASE_INSENSITIVE);
        assertTrue(java.matcher("Java入门与实战").find());
        assertFalse(java.matcher("JavaScript 入门").find());
        assertFalse(java.matcher("MyJava工具").find());
        Pattern cpp=Pattern.compile(ArticlePreferenceService.titlePattern("C++"));
        assertTrue(cpp.matcher("C++ 并发").find());
        assertFalse(cpp.matcher("C 并发").find());
        assertTrue(Pattern.compile(ArticlePreferenceService.titlePattern("分布式系统")).matcher("学习分布式系统").find());
    }
}
