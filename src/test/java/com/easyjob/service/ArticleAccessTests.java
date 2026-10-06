package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.easyjob.vo.ArticleDetailVO;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ArticleAccessTests {
    JdbcTemplate jdbc=mock(JdbcTemplate.class);
    ReadingGrowthService growth=mock(ReadingGrowthService.class);
    ArticleAccessService access=new ArticleAccessService(jdbc,growth,mock(RedisComponent.class),mock(ArticleIndexPublisher.class));
    void progress(Long uid,int level,long seconds) {
        when(growth.summary(uid)).thenReturn(Map.of("level",level,"totalSeconds",seconds));
        when(growth.rules()).thenReturn(List.of(Map.of("level",0,"minSeconds",0L),Map.of("level",1,"minSeconds",3600L)));
    }
    @Test void anonymousAndLowLevelResponsesNeverIncludeFullContent() {
        for(Long uid:new Long[]{null,7L}) {
            progress(uid,0,120);
            var detail=new ArticleDetailVO(); detail.setContent("private body");
            access.apply(detail,uid,99L,1);
            assertFalse(detail.getCanReadFull()); assertNull(detail.getContent());
            assertEquals(3480L,detail.getSecondsToUnlock());
        }
    }
    @Test void qualifiedReaderAndAuthorCanReadButCannotSetPolicy() {
        progress(7L,1,3600);
        var detail=new ArticleDetailVO(); detail.setContent("body");
        access.apply(detail,7L,99L,1); assertTrue(detail.getCanReadFull()); assertEquals("body",detail.getContent());
        progress(7L,0,0); access.apply(detail,7L,7L,1); assertTrue(detail.getCanReadFull());
        assertThrows(BusinessException.class,()->access.setRequiredLevel(42L,7L,1));
        assertTrue(mockingDetails(jdbc).getInvocations().stream().noneMatch(i->i.getMethod().getName().equals("update")));
    }
}
