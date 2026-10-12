package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.*;
import com.easyjob.mapper.ArticleRevisionMapper;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
class ArticleRevisionTests {
    ArticleRevisionMapper store=mock(ArticleRevisionMapper.class);
    ArticleAccessService access=mock(ArticleAccessService.class);
    ArticleIndexPublisher index=mock(ArticleIndexPublisher.class);
    UserMapper users=mock(UserMapper.class);
    com.easyjob.service.impl.NotificationServiceImpl notifications=mock(com.easyjob.service.impl.NotificationServiceImpl.class);
    ArticleRevisionService service=new ArticleRevisionService(store,new ObjectMapper(),mock(ArticleMapper.class),users,mock(ArticleTagService.class),access,index,mock(RedisComponent.class),notifications);
    @BeforeEach void workspaceOwner() {
        when(store.findOwners(42L)).thenReturn(List.of(Map.of("user_id",7L)));
        when(store.lockOwner(7L)).thenReturn(List.of(Map.of("user_id",7L)));
        when(store.findRevisionArticle(5L)).thenReturn(List.of(Map.of("article_id",42L)));
    }
    Map<String,Object> article(){return new HashMap<>(Map.of("article_id",42L,"user_id",7L,"status",1,"latest_revision_id",5L,"published_revision_id",3L));}
    @Test void ordinaryUsersCannotInspectOrApproveRevisionBodies(){
        assertThrows(BusinessException.class,()->service.reviewDetail(7L,99L));
        assertThrows(BusinessException.class,()->service.review(7L,99L,"approve",""));
        verifyNoInteractions(index,users);
    }
    @Test void staleEditorCannotOverwriteLatestRevision(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        var dto=new ArticleCreateDTO();dto.setExpectedRevisionId("4");
        var error=assertThrows(BusinessException.class,()->service.save(7L,42L,dto));
        assertTrue(error.getMessage().contains("版本已变化"));verifyNoInteractions(index,users);
    }
    @Test void privateDraftReadChecksOwnerAndReturnsWorkingRevision(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of(
            "revision_id",5L,"article_id",42L,"state",0,"lock_version",0L,"payload","{\"title\":\"私有修改版\",\"content\":\"完整正文\"}"))));
        assertThrows(BusinessException.class,()->service.ownDraft(8L,42L));
        var draft=service.ownDraft(7L,42L);
        assertEquals("42",draft.get("articleId"));assertEquals("5",draft.get("revisionId"));assertEquals(true,draft.get("editable"));
        assertTrue(draft.get("payload").toString().contains("私有修改版"));
        verify(store,never()).saveWorkingRevision(anyString(),anyString(),anyInt(),anyInt(),anyLong());
        verify(store,never()).insertRevision(any());
    }
    @Test void pendingDraftIsReadableButCannotBeOverwrittenByAgent(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of(
            "revision_id",5L,"article_id",42L,"state",1,"lock_version",0L,"payload","{\"title\":\"审核中\"}"))));
        assertEquals(false,service.ownDraft(7L,42L).get("editable"));
        assertThrows(BusinessException.class,()->service.updateAgentDraft(7L,42L,"5","新标题","","正文"));
        verify(store,never()).saveWorkingRevision(anyString(),anyString(),anyInt(),anyInt(),anyLong());
        verify(store,never()).insertRevision(any());
    }
    @Test void agentUpdateRejectsRevisionChangedInDraftBox(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of(
            "revision_id",5L,"article_id",42L,"state",0,"lock_version",0L,"payload","{\"title\":\"最新修改\",\"content\":\"最新正文\"}"))));
        var error=assertThrows(BusinessException.class,()->service.updateAgentDraft(7L,42L,"4","旧标题","","旧正文"));
        assertTrue(error.getMessage().contains("版本已变化"));verify(store,never()).saveWorkingRevision(anyString(),anyString(),anyInt(),anyInt(),anyLong());
        verify(store,never()).insertRevision(any());
    }
    @Test void agentUpdateKeepsMetadataAndSavesAnUnpublishedRevision(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of(
            "revision_id",5L,"article_id",42L,"state",0,"lock_version",0L,"payload","{\"title\":\"旧标题\",\"content\":\"旧正文\",\"categoryId\":6,\"coverImage\":\"/uploads/cover.png\",\"tagNames\":[\"Java\"],\"isOriginal\":1}"))));
        var spy=spy(service);
        doReturn(Map.of()).when(spy).save(eq(7L),eq(42L),any(ArticleCreateDTO.class));
        spy.updateAgentDraft(7L,42L,"5","修改标题","摘要","<p>正文</p>");
        var capture=org.mockito.ArgumentCaptor.forClass(ArticleCreateDTO.class);
        verify(spy).save(eq(7L),eq(42L),capture.capture());var saved=capture.getValue();
        assertEquals(0,saved.getStatus());assertEquals("5",saved.getExpectedRevisionId());
        assertEquals("/uploads/cover.png",saved.getCoverImage());assertEquals(List.of("Java"),saved.getTagNames());
        assertEquals("6",saved.getCategoryId());assertEquals("修改标题",saved.getTitle());
    }
    @Test void foreignAuthorCannotWithdrawOrReadHistory(){
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        assertThrows(BusinessException.class,()->service.history(8L,42L));
        assertThrows(BusinessException.class,()->service.withdraw(8L,42L,5L));
        verifyNoInteractions(index,users);
    }
    @Test void staleReviewCannotPublishOrCount(){
        when(access.isAdmin(9L)).thenReturn(true);
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of("revision_id",5L,"article_id",42L,"state",4))));
        assertThrows(BusinessException.class,()->service.review(9L,5L,"approve",""));verifyNoInteractions(index,users,notifications);
    }
    @Test void rejectingWithoutReasonIsInvalidBeforeReadingContent(){
        when(access.isAdmin(9L)).thenReturn(true);
        assertThrows(BusinessException.class,()->service.review(9L,5L,"reject"," "));
        verifyNoInteractions(index,users);
    }
    @Test void rejectionUsesReviewedTitleAndVersionAndKeepsPreviewWithinColumnLimit(){
        when(access.isAdmin(9L)).thenReturn(true);
        when(store.lockPublishedArticle(42L)).thenReturn(List.of(article()));
        when(store.lockRevision(5L)).thenReturn(List.of(new HashMap<>(Map.of(
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
