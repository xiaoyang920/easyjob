package com.easyjob.service;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class AdminOperationsTests {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminOperationsService service=new AdminOperationsService(jdbc,admin);
    final String id="e5b1f115-a7d4-4cb8-87a4-50a1200dc531";
    @Test void allEntrypointsRequireAdministratorBeforeQuery() {
        doThrow(new BusinessException(403,"denied")).when(admin).requireAdmin(3L);
        assertThrows(BusinessException.class,()->service.summary(3L));
        assertThrows(BusinessException.class,()->service.jobs(3L,"article","dead",1,20));
        assertThrows(BusinessException.class,()->service.runs(3L,"all",1,20));
        assertThrows(BusinessException.class,()->service.retry(3L,"article",id));
        assertThrows(BusinessException.class,()->service.reconcile(3L,"article"));
        verifyNoInteractions(jdbc);
    }
    @Test void untrustedQueueCannotBecomeSqlIdentifier() {
        assertThrows(BusinessException.class,()->service.jobs(1L,"article;DROP TABLE user_info","all",1,20));
        assertThrows(BusinessException.class,()->service.retry(1L,null,id));
        assertThrows(BusinessException.class,()->service.jobs(1L,"memory",null,1,20));
        assertThrows(BusinessException.class,()->service.runs(1L,"bad",1,20));
        assertThrows(BusinessException.class,()->service.runs(1L,"all",0,20));
        verifyNoInteractions(jdbc);
    }
    void task(String state) {when(jdbc.queryForList("SELECT status,article_id AS target_id FROM article_index_outbox WHERE job_id=? FOR UPDATE",id)).thenReturn(List.of(Map.of("status",state,"target_id",42L)));}
    @Test void activeAndCompletedJobsCannotBeReset() {
        for(String state:List.of("pending","running","dispatched","completed")) {task(state);assertThrows(BusinessException.class,()->service.retry(1L,"article",id));}
        verify(jdbc,never()).update(anyString(),any(Object[].class));
    }
    @Test void deadTaskRetryHasAuditAndClearsOldLease() {
        task("dead");service.retry(1L,"article",id);
        verify(jdbc).update("UPDATE article_index_outbox SET status='pending',attempts=0,lease_until=NULL,lease_token=NULL,last_error=NULL,available_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE job_id=? AND status='dead'",id);
        verify(jdbc).update("INSERT INTO admin_operation_log(admin_user_id,action,target_type,target_id,before_value,after_value) VALUES (?,'task_retry',?,?,?,'pending')",1L,"article",42L,id);
    }
    @Test void retiredExtractionCannotBeRevived() {
        var mid="a".repeat(64);
        when(jdbc.queryForList("SELECT status,user_id AS target_id,kind FROM agent_background_job WHERE job_id=? FOR UPDATE",mid)).thenReturn(List.of(Map.of("status","dead","target_id",2L,"kind","memory_extract")));
        assertThrows(BusinessException.class,()->service.retry(1L,"memory",mid));
        verify(jdbc,never()).update(anyString(),any(Object[].class));
    }
    @Test void reconcileCannotStealActiveLeaseOrAcceptUnknownKind() {
        assertThrows(BusinessException.class,()->service.reconcile(1L,"unknown"));
        assertThrows(BusinessException.class,()->service.reconcile(1L,"article"));
        verify(jdbc).update("UPDATE maintenance_cursor SET next_at=UTC_TIMESTAMP(6) WHERE kind=? AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6)) AND next_at>UTC_TIMESTAMP(6)","article");
    }
}
