package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminCategoryTests {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminCategoryService service=new AdminCategoryService(jdbc,admin,new ObjectMapper());
    AdminCategoryService.Create body(String name,long parent){return new AdminCategoryService.Create(name,parent,0,"");}
    @Test void onlyAdministratorsCanReadOrCreate(){
        doThrow(new BusinessException(403,"禁止")).when(admin).requirePermission(eq(1L),anyString());
        assertEquals(403,assertThrows(BusinessException.class,()->service.list(1L)).getCode());
        assertEquals(403,assertThrows(BusinessException.class,()->service.create(1L,body("后端",0))).getCode());verifyNoInteractions(jdbc);
    }
    @Test void boundsAndControlCharactersAreRejectedBeforeWrites(){
        for(var b:List.of(body("  ",0),body("a".repeat(51),0),body("后\n端",0),body("后端",-1),new AdminCategoryService.Create("后端",0L,10000,""),new AdminCategoryService.Create("后端",0L,0,"a".repeat(201))))assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,b)).getCode());
        verifyNoInteractions(jdbc);
    }
    @Test void parentMustExistBeEnabledAndTopLevel(){
        when(jdbc.queryForList(contains("FOR UPDATE"),any(Object[].class))).thenReturn(List.of());
        assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,body("Java",3))).getCode());
        for(var row:List.of(Map.<String,Object>of("parent_id",0L,"status",0),Map.<String,Object>of("parent_id",3L,"status",1))){
            when(jdbc.queryForList(contains("FOR UPDATE"),any(Object[].class))).thenReturn(List.of(row));
            assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,body("Java",3))).getCode());
        }
        verify(jdbc,never()).update(anyString(),any(Object[].class));
    }
    @Test void duplicateNamesReturnConflictAndDoNotAudit(){
        when(jdbc.update(startsWith("INSERT INTO category("),any(Object[].class))).thenThrow(new DuplicateKeyException("unique"));
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(2L,body("后端",0))).getCode());
        verify(jdbc,never()).update(startsWith("INSERT INTO admin_operation_log"),any(Object[].class));
    }
    @Test void createdCategoryGetsBackendIdNormalizationAndAudit(){
        var result=service.create(2L,body("  Ｊａｖａ  ",0));
        assertEquals("Java",result.get("categoryName"));assertTrue(Long.parseLong((String)result.get("categoryId"))>0);assertEquals("0",result.get("parentId"));assertEquals(1,result.get("status"));
        verify(jdbc).update(startsWith("INSERT INTO admin_operation_log"),any(Object[].class));
    }
    @Test void enabledRootCanReceiveSubcategory(){
        when(jdbc.queryForList(contains("FOR UPDATE"),any(Object[].class))).thenReturn(List.of(Map.of("parent_id",0L,"status",1)));
        assertEquals("3",service.create(2L,body("Java",3)).get("parentId"));
    }
}
