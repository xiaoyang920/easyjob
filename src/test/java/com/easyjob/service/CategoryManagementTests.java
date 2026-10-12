package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AdminCategoryManagementMapper;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class CategoryManagementTests {
    final AdminCategoryManagementMapper store=mock(AdminCategoryManagementMapper.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminCategoryManagementService service=new AdminCategoryManagementService(store,admin,new ObjectMapper(),mock(RedisComponent.class),mock(ArticleIndexPublisher.class));
    void source(long version){when(store.findParent(anyLong())).thenReturn(List.of(Map.of("parent_id",0L)));when(store.lockCategory(anyLong())).thenReturn(List.of(Map.of("category_id",3L,"category_name","后端","parent_id",0L,"status",1,"version",version)));}
    @Test void unauthorizedEditsAndMigrationDoNotTouchDatabase(){doThrow(new BusinessException(403,"禁止")).when(admin).requirePermission(1L,"categories.manage");assertThrows(BusinessException.class,()->service.update(1L,3,new AdminCategoryManagementService.Update(0L,"后端",0,"",1)));assertThrows(BusinessException.class,()->service.move(1L,3,new AdminCategoryManagementService.Move(0L,4L,0L)));verifyNoInteractions(store);}
    @Test void staleVersionCannotOverwriteNewerCategory(){source(2);assertEquals(409,assertThrows(BusinessException.class,()->service.update(2L,3,new AdminCategoryManagementService.Update(1L,"后端",0,"",1))).getCode());assertTrue(mockingDetails(store).getInvocations().stream().noneMatch(i->Set.of("incrementVersion","redirectCategory","moveArticle","updateCategory","insertAudit").contains(i.getMethod().getName())));}
    @Test void parentWithEnabledChildrenCannotBeDisabled(){source(0);when(store.lockEnabledChildren(anyLong())).thenReturn(List.of(Map.of("category_id",4L)));assertEquals(409,assertThrows(BusinessException.class,()->service.update(2L,3,new AdminCategoryManagementService.Update(0L,"后端",0,"",0))).getCode());}
    @Test void categoryRedirectsUseCurrentReadsAndDetectCycles(){
        var store=mock(com.easyjob.mapper.ArticleRevisionMapper.class);
        when(store.lockCategoryRedirect(3L)).thenReturn(List.of(Map.of("migrated_to",4L)));
        when(store.lockCategoryRedirect(4L)).thenReturn(List.of(Map.of("category_id",4L)));
        assertEquals(4L,CategoryRouting.resolve(store,3L));
        when(store.lockCategoryRedirect(4L)).thenReturn(List.of(Map.of("migrated_to",3L)));
        assertEquals(409,assertThrows(BusinessException.class,()->CategoryRouting.resolve(store,3L)).getCode());
    }
}
