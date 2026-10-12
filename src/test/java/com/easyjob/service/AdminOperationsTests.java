package com.easyjob.service;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AdminOperationsMapper;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class AdminOperationsTests {
    final AdminOperationsMapper store=mock(AdminOperationsMapper.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminOperationsService service=new AdminOperationsService(store,admin);
    final String id="e5b1f115-a7d4-4cb8-87a4-50a1200dc531";
    @Test void allEntrypointsRequireAdministratorBeforeQuery() {
        doThrow(new BusinessException(403,"denied")).when(admin).requirePermission(eq(3L),anyString());
        assertThrows(BusinessException.class,()->service.summary(3L));
        assertThrows(BusinessException.class,()->service.jobs(3L,"article","dead",1,20));
        assertThrows(BusinessException.class,()->service.runs(3L,"all",1,20));
        assertThrows(BusinessException.class,()->service.retry(3L,"article",id));
        assertThrows(BusinessException.class,()->service.reconcile(3L,"article"));
        verifyNoInteractions(store);
    }
    @Test void untrustedQueueCannotBecomeSqlIdentifier() {
        assertThrows(BusinessException.class,()->service.jobs(1L,"article;DROP TABLE user_info","all",1,20));
        assertThrows(BusinessException.class,()->service.retry(1L,null,id));
        assertThrows(BusinessException.class,()->service.jobs(1L,"memory",null,1,20));
        assertThrows(BusinessException.class,()->service.runs(1L,"bad",1,20));
        assertThrows(BusinessException.class,()->service.runs(1L,"all",0,20));
        verifyNoInteractions(store);
    }
    void task(String state) {when(store.lockJob("article",id)).thenReturn(List.of(Map.of("status",state,"target_id",42L)));}
    @Test void activeAndCompletedJobsCannotBeReset() {
        for(String state:List.of("pending","running","dispatched","completed")) {task(state);assertThrows(BusinessException.class,()->service.retry(1L,"article",id));}
        verify(store,never()).retryJob(anyString(),anyString());
    }
    @Test void deadTaskRetryHasAuditAndClearsOldLease() {
        task("dead");service.retry(1L,"article",id);
        verify(store).retryJob("article",id);
        verify(store).insertRetryAudit(1L,"article",42L,id);
    }
    @Test void retiredExtractionCannotBeRevived() {
        var mid="a".repeat(64);
        when(store.lockJob("memory",mid)).thenReturn(List.of(Map.of("status","dead","target_id",2L,"kind","memory_extract")));
        assertThrows(BusinessException.class,()->service.retry(1L,"memory",mid));
        verify(store,never()).retryJob(anyString(),anyString());
    }
    @Test void reconcileCannotStealActiveLeaseOrAcceptUnknownKind() {
        assertThrows(BusinessException.class,()->service.reconcile(1L,"unknown"));
        assertThrows(BusinessException.class,()->service.reconcile(1L,"article"));
        verify(store).scheduleReconciliation("article");
    }
}
