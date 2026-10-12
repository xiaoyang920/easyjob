package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import com.easyjob.mapper.AdminCategoryMapper;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminCategoryTests {
    final AdminCategoryMapper store=mock(AdminCategoryMapper.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminCategoryService service=new AdminCategoryService(store,admin,new ObjectMapper());
    AdminCategoryService.Create body(String name,long parent){return new AdminCategoryService.Create(name,parent,0,"");}
    @Test void onlyAdministratorsCanReadOrCreate(){
        doThrow(new BusinessException(403,"禁止")).when(admin).requirePermission(eq(1L),anyString());
        assertEquals(403,assertThrows(BusinessException.class,()->service.list(1L)).getCode());
        assertEquals(403,assertThrows(BusinessException.class,()->service.create(1L,body("后端",0))).getCode());verifyNoInteractions(store);
    }
    @Test void boundsAndControlCharactersAreRejectedBeforeWrites(){
        for(var b:List.of(body("  ",0),body("a".repeat(51),0),body("后\n端",0),body("后端",-1),new AdminCategoryService.Create("后端",0L,10000,""),new AdminCategoryService.Create("后端",0L,0,"a".repeat(201))))assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,b)).getCode());
        verifyNoInteractions(store);
    }
    @Test void parentMustExistBeEnabledAndTopLevel(){
        when(store.lockParent(anyLong())).thenReturn(List.of());
        assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,body("Java",3))).getCode());
        for(var row:List.of(Map.<String,Object>of("parent_id",0L,"status",0),Map.<String,Object>of("parent_id",3L,"status",1))){
            when(store.lockParent(anyLong())).thenReturn(List.of(row));
            assertEquals(400,assertThrows(BusinessException.class,()->service.create(2L,body("Java",3))).getCode());
        }
        assertTrue(mockingDetails(store).getInvocations().stream().noneMatch(i->Set.of("insertCreateAudit","insertCategory").contains(i.getMethod().getName())));
    }
    @Test void duplicateNamesReturnConflictAndDoNotAudit(){
        when(store.insertCategory(anyLong(),any(),anyLong(),anyInt(),any())).thenThrow(new DuplicateKeyException("unique"));
        assertEquals(409,assertThrows(BusinessException.class,()->service.create(2L,body("后端",0))).getCode());
        verify(store,never()).insertCreateAudit(any(),anyLong(),any(),any());
    }
    @Test void createdCategoryGetsBackendIdNormalizationAndAudit(){
        var result=service.create(2L,body("  Ｊａｖａ  ",0));
        assertEquals("Java",result.get("categoryName"));assertTrue(Long.parseLong((String)result.get("categoryId"))>0);assertEquals("0",result.get("parentId"));assertEquals(1,result.get("status"));
        verify(store).insertCreateAudit(any(),anyLong(),any(),any());
    }
    @Test void enabledRootCanReceiveSubcategory(){
        when(store.lockParent(anyLong())).thenReturn(List.of(Map.of("parent_id",0L,"status",1)));
        assertEquals("3",service.create(2L,body("Java",3)).get("parentId"));
    }
}
