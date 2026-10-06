package com.easyjob.service;

import com.easyjob.component.ArticleViewSync;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleReadTests {
    @Test void durableProjectionIsEnqueuedOnlyForANewQualifiedRead() {
        var jdbc=mock(JdbcTemplate.class); var sync=mock(ArticleViewSync.class); var access=mock(ArticleAccessService.class);
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(Map.of("user_id",99L,"status",1,"deleted",0,"view_count",8,"required_level",0)));
        when(access.canRead(7L,99L,0)).thenReturn(true);
        when(jdbc.update(startsWith("INSERT IGNORE INTO article_read_receipt"),any(),any(),any())).thenReturn(1,0);
        var service=new ArticleReadService(jdbc,sync,access);
        assertEquals(Map.of("counted",true,"viewCount",9),service.record(42L,7L,"a".repeat(64)));
        assertEquals(Map.of("counted",false,"viewCount",8),service.record(42L,7L,"a".repeat(64)));
        verify(sync,times(1)).enqueue(42L,9);
    }
    @Test void deniedReadDoesNotCreateReceiptOrProjection() {
        var jdbc=mock(JdbcTemplate.class); var sync=mock(ArticleViewSync.class);
        var access=mock(ArticleAccessService.class);
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(Map.of("user_id",99L,"status",1,"deleted",0,"view_count",8,"required_level",2)));
        assertThrows(com.easyjob.exception.BusinessException.class,()->new ArticleReadService(jdbc,sync,access).record(42L,7L,"a".repeat(64)));
        verifyNoInteractions(sync);
        verify(jdbc,never()).update(anyString(),any(Object[].class));
    }
}
