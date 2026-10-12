package com.easyjob.service;

import com.easyjob.component.RedisComponent;
import com.easyjob.config.ArticleWebSocketHandler;
import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AdminUserMapper;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminUserTests {
    final AdminUserMapper store=mock(AdminUserMapper.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final ReadingGrowthService growth=mock(ReadingGrowthService.class);
    final RedisComponent redis=mock(RedisComponent.class);
    final ArticleWebSocketHandler articles=mock(ArticleWebSocketHandler.class);
    final ChatWebSocketHandler chats=mock(ChatWebSocketHandler.class);
    final AdminUserService service=new AdminUserService(store,admin,growth,redis,articles,chats);
    final AdminUserService.Profile ordinary=new AdminUserService.Profile("小明",null,1,1);
    Map<String,Object> row(long id,String name,int role,int status){return new HashMap<>(Map.of("userId",Long.toString(id),"nickName",name,"role",role,"status",status));}
    void lock(){when(store.lockActorAndUser(eq(7L),eq(8L)))
            .thenReturn(List.of(row(7,"管理员",2,1),row(8,"小明",1,1)));}
    AdminUserService.Update body(AdminUserService.Profile expected,int role,int status,Long seconds,String millis){
        return new AdminUserService.Update(expected,"小明","新的简介",role,status,seconds,millis,"用户反馈，管理员校正");
    }
    @AfterEach void clear(){if(TransactionSynchronizationManager.isSynchronizationActive())TransactionSynchronizationManager.clearSynchronization();}
    void noWrites(){assertTrue(mockingDetails(store).getInvocations().stream().noneMatch(i->Set.of("insertAudit","updateProfile","correctProgress","ensureProgress").contains(i.getMethod().getName())));}
    @Test void onlyAdministratorsCanReadOrWrite(){
        doThrow(new BusinessException(403,"无权限")).when(admin).requireAdmin(9L);
        assertEquals(403,assertThrows(BusinessException.class,()->service.detail(9L,8L)).getCode());
        assertEquals(403,assertThrows(BusinessException.class,()->service.update(9L,8L,body(ordinary,1,1,null,null))).getCode());
        verifyNoInteractions(store);
    }
    @Test void roleStatusAndReasonAreValidatedBeforeAnyWrite(){
        assertEquals(400,assertThrows(BusinessException.class,()->service.update(7L,8L,body(ordinary,9,1,null,null))).getCode());
        assertEquals(400,assertThrows(BusinessException.class,()->service.update(7L,8L,body(ordinary,1,2,null,null))).getCode());
        assertThrows(BusinessException.class,()->service.update(7L,8L,new AdminUserService.Update(ordinary,"小明",null,1,1,null,null," ")));
        assertThrows(BusinessException.class,()->service.update(7L,8L,body(ordinary,1,1,-1L,"0")));
        verifyNoInteractions(store);
    }
    @Test void permissionIsRecheckedAfterLock(){
        when(store.lockActorAndUser(eq(7L),eq(8L)))
                .thenReturn(List.of(row(7,"前管理员",1,1),row(8,"小明",1,1)));
        assertEquals(403,assertThrows(BusinessException.class,()->service.update(7L,8L,body(ordinary,1,1,null,null))).getCode());noWrites();
    }
    @Test void staleProfileDoesNotOverwriteConcurrentEdit(){
        lock();var stale=new AdminUserService.Profile("旧昵称",null,1,1);
        assertEquals(409,assertThrows(BusinessException.class,()->service.update(7L,8L,body(stale,1,1,null,null))).getCode());noWrites();
    }
    @Test void administratorsCannotRemoveTheirOwnAccess(){
        when(store.lockActorAndUser(eq(7L),eq(7L))).thenReturn(List.of(row(7,"管理员",2,1)));
        var self=new AdminUserService.Profile("管理员",null,2,1);
        assertEquals(409,assertThrows(BusinessException.class,()->service.update(7L,7L,body(self,1,1,null,null))).getCode());
        assertEquals(409,assertThrows(BusinessException.class,()->service.update(7L,7L,body(self,2,0,null,null))).getCode());noWrites();
    }
    @Test void accountChangesRevokeSessionsOnlyAfterCommitAndAreAudited(){
        lock();TransactionSynchronizationManager.initSynchronization();
        service.update(7L,8L,body(ordinary,1,0,null,null));
        verify(store).updateProfile(eq("小明"),eq("新的简介"),eq(1),eq(0),eq(1),eq(8L));
        verify(store).insertAudit(eq(7L),eq(8L),anyString(),anyString(),eq("用户反馈，管理员校正"),contains("新的简介"));
        verifyNoInteractions(redis,articles,chats);
        TransactionSynchronizationManager.getSynchronizations().forEach(s->s.afterCommit());
        verify(redis).deleteUserSpaceVO(8L);verify(articles).disconnectUser(8L);verify(chats).disconnectUser(8L);
    }
    @Test void correctingGrowthRecomputesLevelAndInvalidatesActiveTimer(){
        lock();TransactionSynchronizationManager.initSynchronization();
        when(store.lockProgress(eq(8L))).thenReturn(Map.of("total_millis",3600000L,"earned_level",3));
        when(growth.rules()).thenReturn(List.of(Map.of("level",0,"minSeconds",0L),Map.of("level",1,"minSeconds",3600L)));
        service.update(7L,8L,body(ordinary,1,1,10L,"3600000"));
        verify(store).correctProgress(eq(10000L),eq(0),eq(8L));
        verify(store).updateProfile(any(),any(),any(),any(),eq(0),eq(8L));
        verifyNoInteractions(articles,chats);
    }
    @Test void activeReadingRequiresExplicitFreshSnapshotForCorrection(){
        lock();when(store.lockProgress(eq(8L))).thenReturn(Map.of("total_millis",100L,"earned_level",0));
        assertEquals(409,assertThrows(BusinessException.class,()->service.update(7L,8L,body(ordinary,1,1,10L,"0"))).getCode());
        verify(store,never()).updateProfile(any(),any(),any(),any(),anyInt(),any());
        verify(store,never()).correctProgress(anyLong(),anyInt(),any());
    }
    @Test void unchangedFormDoesNotCreateAuditOrRevokeLogin(){
        lock();service.update(7L,8L,new AdminUserService.Update(ordinary,"小明",null,1,1,null,null,"检查确认"));noWrites();
        verifyNoInteractions(redis,articles,chats);
    }
}
