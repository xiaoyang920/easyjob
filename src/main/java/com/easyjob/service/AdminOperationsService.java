package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

/** Operational metadata only: never expose prompts, results, job payloads or lease tokens. */
@Service @RequiredArgsConstructor
public class AdminOperationsService {
    private final JdbcTemplate jdbc;
    private final AdminConsoleService admin;
    private static final Map<String,String> QUEUES=Map.of("memory","agent_background_job","article","article_index_outbox");
    private static final Set<String> KINDS=Set.of("article","memory","article_orphan","memory_orphan","chunk_orphan");
    public Map<String,Object> summary(Long uid) {
        admin.requirePermission(uid,"operations.read");var result=new LinkedHashMap<String,Object>();
        for(var queue:QUEUES.entrySet()) result.put(queue.getKey(),jdbc.queryForList("SELECT status,COUNT(*) AS count,COALESCE(MAX(TIMESTAMPDIFF(SECOND,created_at,UTC_TIMESTAMP(6))),0) AS oldestSeconds FROM "+queue.getValue()+" GROUP BY status"));
        result.put("runs",jdbc.queryForList("SELECT status,COUNT(*) AS count FROM agent_run WHERE created_at>=TIMESTAMPADD(DAY,-1,NOW(6)) GROUP BY status"));
        result.put("views",jdbc.queryForMap("SELECT COUNT(*) AS pending,COALESCE(MAX(attempts),0) AS maxAttempts FROM article_view_sync"));
        result.put("reconciliation",jdbc.queryForList("SELECT kind,last_id AS lastId,scanned,repaired,last_error AS error,next_at AS nextAt,last_finished_at AS finishedAt,(lease_until>UTC_TIMESTAMP(6)) AS running FROM maintenance_cursor ORDER BY kind"));
        return result;
    }
    public PageVO<Map<String,Object>> jobs(Long uid,String queue,String state,int page,int size) {
        admin.requirePermission(uid,"operations.read");String table=QUEUES.get(queue==null?"":queue);
        if(table==null || !Set.of("all","pending","running","dispatched","completed","dead").contains(state==null?"":state))throw new BusinessException(400,"任务筛选无效");
        ArticleRevisionService.bounds(page,size);
        String where=state.equals("all")?"":" WHERE status=?";var args=new ArrayList<Object>();if(!state.equals("all"))args.add(state);
        long count=jdbc.queryForObject("SELECT COUNT(*) FROM "+table+where,Long.class,args.toArray());
        args.add(size);args.add((page-1)*size);
        String identity=queue.equals("article")?"CAST(article_id AS CHAR) AS targetId,action AS kind":"CAST(user_id AS CHAR) AS targetId,kind";
        var rows=jdbc.queryForList("SELECT job_id AS jobId,"+identity+",status,attempts,available_at AS availableAt,updated_at AS updatedAt,CASE WHEN last_error REGEXP '^[a-zA-Z0-9_]{1,128}$' THEN last_error ELSE 'task_failed' END AS error FROM "+table+where+" ORDER BY updated_at DESC,job_id DESC LIMIT ? OFFSET ?",args.toArray());
        return new PageVO<>(rows,count,(long)size,(long)page,(count+size-1)/size);
    }
    public PageVO<Map<String,Object>> runs(Long uid,String state,int page,int size) {
        admin.requirePermission(uid,"operations.read");ArticleRevisionService.bounds(page,size);
        if(!Set.of("all","running","awaiting_approval","succeeded","failed","cancelled","expired").contains(state==null?"":state))throw new BusinessException(400,"运行筛选无效");
        var args=new ArrayList<Object>();String where=state.equals("all")?"":" WHERE status=?";if(!state.equals("all"))args.add(state);
        long count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_run"+where,Long.class,args.toArray());args.add(size);args.add((page-1)*size);
        var rows=jdbc.queryForList("SELECT run_id AS runId,CAST(user_id AS CHAR) AS userId,CAST(conversation_id AS CHAR) AS conversationId,status,DATE_FORMAT(TIMESTAMPADD(SECOND,-TIMESTAMPDIFF(SECOND,UTC_TIMESTAMP(),NOW()),created_at),'%Y-%m-%dT%H:%i:%sZ') AS createdAt,updated_at AS updatedAt,deadline FROM agent_run"+where+" ORDER BY created_at DESC,run_id DESC LIMIT ? OFFSET ?",args.toArray());
        return new PageVO<>(rows,count,(long)size,(long)page,(count+size-1)/size);
    }
    @Transactional public void retry(Long uid,String queue,String id) {
        admin.requirePermission(uid,"operations.manage");String table=QUEUES.get(queue==null?"":queue);
        if(table==null || id==null || !id.matches(queue.equals("article")?"[a-f0-9-]{36}":"[a-f0-9]{64}"))throw new BusinessException(400,"任务标识无效");
        var rows=jdbc.queryForList("SELECT status,"+(queue.equals("article")?"article_id":"user_id")+" AS target_id"+(queue.equals("memory")?",kind":"")+" FROM "+table+" WHERE job_id=? FOR UPDATE",id);
        if(rows.isEmpty())throw new BusinessException(404,"任务不存在");var row=rows.getFirst();
        if(!"dead".equals(row.get("status")))throw new BusinessException(409,"只能重试已终止的失败任务，请刷新状态");
        if(queue.equals("memory") && !Set.of("memory_write","memory_index","checkpoint_cleanup").contains(row.get("kind")))throw new BusinessException(409,"该任务类型已停用，不能重试");
        jdbc.update("UPDATE "+table+" SET status='pending',attempts=0,lease_until=NULL,lease_token=NULL,last_error=NULL,available_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE job_id=? AND status='dead'",id);
        jdbc.update("INSERT INTO admin_operation_log(admin_user_id,action,target_type,target_id,before_value,after_value) VALUES (?,'task_retry',?,?,?,'pending')",uid,queue,((Number)row.get("target_id")).longValue(),id);
    }
    @Transactional public void reconcile(Long uid,String kind) {
        admin.requirePermission(uid,"operations.manage");if(!KINDS.contains(kind==null?"":kind))throw new BusinessException(400,"对账类型无效");
        int changed=jdbc.update("UPDATE maintenance_cursor SET next_at=UTC_TIMESTAMP(6) WHERE kind=? AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6)) AND next_at>UTC_TIMESTAMP(6)",kind);
        if(changed==0)throw new BusinessException(409,"对账已在等待或执行中，请稍后刷新");
        jdbc.update("INSERT INTO admin_operation_log(admin_user_id,action,target_type,target_id,before_value,after_value) VALUES (?,'index_reconcile','maintenance',?,'idle',?)",uid,uid,kind);
    }
}
