package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
class ArticleRevisionTests {
    JdbcTemplate jdbc=mock(JdbcTemplate.class);
    ArticleAccessService access=mock(ArticleAccessService.class);
    ArticleIndexPublisher index=mock(ArticleIndexPublisher.class);
    UserMapper users=mock(UserMapper.class);
    com.easyjob.service.impl.NotificationServiceImpl notifications=mock(com.easyjob.service.impl.NotificationServiceImpl.class);
    ArticleRevisionService service=new ArticleRevisionService(jdbc,new ObjectMapper(),mock(ArticleMapper.class),users,mock(ArticleTagService.class),access,index,mock(RedisComponent.class),notifications);
    Map<String,Object> article(){return new HashMap<>(Map.of("article_id",42L,"user_id",7L,"status",1,"latest_revision_id",5L,"published_revision_id",3L));}
    @Test void ordinaryUsersCannotInspectOrApproveRevisionBodies(){
        assertThrows(BusinessException.class,()->service.reviewDetail(7L,99L));
        assertThrows(BusinessException.class,()->service.review(7L,99L,"approve",""));
        verifyNoInteractions(jdbc,index,users);
    }
    @Test void staleEditorCannotOverwriteLatestRevision(){
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(article()));
        var dto=new ArticleCreateDTO();dto.setExpectedRevisionId("4");
        var error=assertThrows(BusinessException.class,()->service.save(7L,42L,dto));
        assertTrue(error.getMessage().contains("版本已变化"));verifyNoInteractions(index,users);
    }
    @Test void foreignAuthorCannotWithdrawOrReadHistory(){
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(article()));
        assertThrows(BusinessException.class,()->service.history(8L,42L));
        assertThrows(BusinessException.class,()->service.withdraw(8L,42L,5L));
        verifyNoInteractions(index,users);
    }
    @Test void staleReviewCannotPublishOrCount(){
        when(access.isAdmin(9L)).thenReturn(true);
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(article()));
        when(jdbc.queryForList(contains("FROM article_revision"),eq(5L))).thenReturn(List.of(new HashMap<>(Map.of("revision_id",5L,"article_id",42L,"state",4))));
        assertThrows(BusinessException.class,()->service.review(9L,5L,"approve",""));verifyNoInteractions(index,users,notifications);
    }
    @Test void rejectingWithoutReasonIsInvalidBeforeReadingContent(){
        when(access.isAdmin(9L)).thenReturn(true);
        assertThrows(BusinessException.class,()->service.review(9L,5L,"reject"," "));
        verifyNoInteractions(jdbc,index,users);
    }
    @Test void rejectionUsesReviewedTitleAndVersionAndKeepsPreviewWithinColumnLimit(){
        when(access.isAdmin(9L)).thenReturn(true);
        when(jdbc.queryForList(contains("FROM article_info"),eq(42L))).thenReturn(List.of(article()));
        when(jdbc.queryForList(contains("FROM article_revision"),eq(5L))).thenReturn(List.of(new HashMap<>(Map.of(
            "revision_id",5L,"article_id",42L,"state",1,"version_no",2,"payload","{\"title\":\"被审核的修改标题\"}"))));
        service.review(9L,5L,"reject","请补充示例".repeat(80));
        var captured=org.mockito.ArgumentCaptor.forClass(com.easyjob.dto.NotificationMessage.class);
        verify(notifications).send(captured.capture());var msg=captured.getValue();
        assertEquals(7,msg.getType());assertEquals(7L,msg.getUserId());assertEquals(5L,msg.getTargetId());
        assertEquals("被审核的修改标题",msg.getArticleTitle());assertTrue(msg.getContent().contains("V2"));
        assertTrue(msg.getTargetPreview().length()<=200);assertTrue(msg.getTargetPreview().endsWith("…"));
        verifyNoInteractions(index);
    }
}
