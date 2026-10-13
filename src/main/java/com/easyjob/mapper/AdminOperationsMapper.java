package com.easyjob.mapper;
import com.easyjob.agent.rpc.AgentRpcClient;
import org.springframework.stereotype.Component;
import java.util.*;

/** Permission-checked admin facade: local blog SQL plus typed Agent RPC. */
@Component
public class AdminOperationsMapper {
    private final AdminBlogOperationsMapper blog;
    private final AgentRpcClient agent;
    public AdminOperationsMapper(AdminBlogOperationsMapper blog,AgentRpcClient agent) { this.blog=blog;this.agent=agent; }
    @SuppressWarnings("unchecked") private List<Map<String,Object>> rows(String kind) { return (List<Map<String,Object>>)agent.serviceQuery(1,kind,"","",1,20,""); }
    @SuppressWarnings("unchecked") private Map<String,Object> page(String kind,String state,int size,int offset) { return (Map<String,Object>)agent.serviceQuery(1,kind,state,"",offset/size+1,size,""); }
    public int insertReconcileAudit(Long actorId,Long targetId,String kind) { return blog.insertReconcileAudit(actorId,targetId,kind); }
    public int insertRetryAudit(Long actorId,String queue,long targetId,String jobId) { return blog.insertRetryAudit(actorId,queue,targetId,jobId); }
    public int scheduleReconciliation(String kind,Long actor) { agent.serviceQuery(actor,"reconcile","",kind,1,20,UUID.randomUUID().toString());return 1; }
    public List<Map<String,Object>> reconciliationSummary() { return rows("reconcile_summary"); }
    public Map<String,Object> viewSummary() { return blog.viewSummary(); }
    public List<Map<String,Object>> runSummary() { return rows("run_summary"); }
    public List<Map<String,Object>> queueSummary(String queue) { return queue.equals("article")?blog.queueSummary(queue):rows("memory_summary"); }
    public Long countJobs(String queue,String state) { return queue.equals("article")?blog.countJobs(queue,state):((Number)page("memory_jobs",state,1,0).get("total")).longValue(); }
    @SuppressWarnings("unchecked") public List<Map<String,Object>> findJobs(String queue,String state,int size,int offset) { return queue.equals("article")?blog.findJobs(queue,state,size,offset):(List<Map<String,Object>>)page("memory_jobs",state,size,offset).get("rows"); }
    public Long countRuns(String state) { return ((Number)page("runs",state,1,0).get("total")).longValue(); }
    @SuppressWarnings("unchecked") public List<Map<String,Object>> findRuns(String state,int size,int offset) { return (List<Map<String,Object>>)page("runs",state,size,offset).get("rows"); }
    public List<Map<String,Object>> lockJob(String queue,String id) { return blog.lockJob(queue,id); }
    public int retryJob(String queue,String id) { return blog.retryJob(queue,id); }
    public void retryMemory(Long actor,String id) { agent.serviceQuery(actor,"memory_retry","",id,1,20,UUID.randomUUID().toString()); }
}
