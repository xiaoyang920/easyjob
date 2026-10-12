package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.PageVO;
import lombok.RequiredArgsConstructor;
import com.easyjob.mapper.AdminOperationsMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

/** Operational metadata only: never expose prompts, results, job payloads or lease tokens. */
@Service @RequiredArgsConstructor
public class AdminOperationsService {
    private final AdminOperationsMapper store;
    private final AdminConsoleService admin;
    private static final Set<String> QUEUES=Set.of("memory","article");
    private static final Set<String> KINDS=Set.of("article","memory","article_orphan","memory_orphan","chunk_orphan");
    public Map<String,Object> summary(Long uid) {
        admin.requirePermission(uid,"operations.read");var result=new LinkedHashMap<String,Object>();
        for(var queue:QUEUES) result.put(queue,store.queueSummary(queue));
        result.put("runs",store.runSummary());
        result.put("views",store.viewSummary());
        result.put("reconciliation",store.reconciliationSummary());
        return result;
    }
    public PageVO<Map<String,Object>> jobs(Long uid,String queue,String state,int page,int size) {
        admin.requirePermission(uid,"operations.read");boolean knownQueue=QUEUES.contains(queue==null?"":queue);
        if(!knownQueue || !Set.of("all","pending","running","dispatched","completed","dead").contains(state==null?"":state))throw new BusinessException(400,"任务筛选无效");
        ArticleRevisionService.bounds(page,size);
        long count=store.countJobs(queue,state);
        var rows=store.findJobs(queue,state,size,(page-1)*size);
        return new PageVO<>(rows,count,(long)size,(long)page,(count+size-1)/size);
    }
    public PageVO<Map<String,Object>> runs(Long uid,String state,int page,int size) {
        admin.requirePermission(uid,"operations.read");ArticleRevisionService.bounds(page,size);
        if(!Set.of("all","running","awaiting_approval","succeeded","failed","cancelled","expired").contains(state==null?"":state))throw new BusinessException(400,"运行筛选无效");
        long count=store.countRuns(state);
        var rows=store.findRuns(state,size,(page-1)*size);
        return new PageVO<>(rows,count,(long)size,(long)page,(count+size-1)/size);
    }
    @Transactional public void retry(Long uid,String queue,String id) {
        admin.requirePermission(uid,"operations.manage");boolean knownQueue=QUEUES.contains(queue==null?"":queue);
        if(!knownQueue || id==null || !id.matches(queue.equals("article")?"[a-f0-9-]{36}":"[a-f0-9]{64}"))throw new BusinessException(400,"任务标识无效");
        var rows=store.lockJob(queue,id);
        if(rows.isEmpty())throw new BusinessException(404,"任务不存在");var row=rows.getFirst();
        if(!"dead".equals(row.get("status")))throw new BusinessException(409,"只能重试已终止的失败任务，请刷新状态");
        if(queue.equals("memory") && !Set.of("memory_write","memory_index","checkpoint_cleanup").contains(row.get("kind")))throw new BusinessException(409,"该任务类型已停用，不能重试");
        store.retryJob(queue,id);
        store.insertRetryAudit(uid,queue,((Number)row.get("target_id")).longValue(),id);
    }
    @Transactional public void reconcile(Long uid,String kind) {
        admin.requirePermission(uid,"operations.manage");if(!KINDS.contains(kind==null?"":kind))throw new BusinessException(400,"对账类型无效");
        int changed=store.scheduleReconciliation(kind);
        if(changed==0)throw new BusinessException(409,"对账已在等待或执行中，请稍后刷新");
        store.insertReconcileAudit(uid,uid,kind);
    }
}
