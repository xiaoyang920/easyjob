package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class CategoryManagementTests {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminCategoryManagementService service=new AdminCategoryManagementService(jdbc,admin,new ObjectMapper(),mock(RedisComponent.class),mock(ArticleIndexPublisher.class));
    void source(long version){when(jdbc.queryForList(startsWith("SELECT parent_id"),any(Object[].class))).thenReturn(List.of(Map.of("parent_id",0L)));when(jdbc.queryForList(startsWith("SELECT * FROM category"),any(Object[].class))).thenReturn(List.of(Map.of("category_id",3L,"category_name","后端","parent_id",0L,"status",1,"version",version)));}
    @Test void unauthorizedEditsAndMigrationDoNotTouchDatabase(){doThrow(new BusinessException(403,"禁止")).when(admin).requirePermission(1L,"categories.manage");assertThrows(BusinessException.class,()->service.update(1L,3,new AdminCategoryManagementService.Update(0L,"后端",0,"",1)));assertThrows(BusinessException.class,()->service.move(1L,3,new AdminCategoryManagementService.Move(0L,4L,0L)));verifyNoInteractions(jdbc);}
    @Test void staleVersionCannotOverwriteNewerCategory(){source(2);assertEquals(409,assertThrows(BusinessException.class,()->service.update(2L,3,new AdminCategoryManagementService.Update(1L,"后端",0,"",1))).getCode());verify(jdbc,never()).update(anyString(),any(Object[].class));}
    @Test void parentWithEnabledChildrenCannotBeDisabled(){source(0);when(jdbc.queryForList(startsWith("SELECT category_id FROM category WHERE parent_id"),any(Object[].class))).thenReturn(List.of(Map.of("category_id",4L)));assertEquals(409,assertThrows(BusinessException.class,()->service.update(2L,3,new AdminCategoryManagementService.Update(0L,"后端",0,"",0))).getCode());}
    @Test void categoryRedirectsUseCurrentReadsAndDetectCycles(){when(jdbc.queryForList(contains("migrated_to"),eq(3L))).thenReturn(List.of(Map.of("migrated_to",4L)));when(jdbc.queryForList(contains("migrated_to"),eq(4L))).thenReturn(List.of());assertEquals(4L,CategoryRouting.resolve(jdbc,3L));when(jdbc.queryForList(contains("migrated_to"),eq(4L))).thenReturn(List.of(Map.of("migrated_to",3L)));assertEquals(409,assertThrows(BusinessException.class,()->CategoryRouting.resolve(jdbc,3L)).getCode());}
}
