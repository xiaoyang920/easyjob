package com.easyjob.mapper;
import com.easyjob.agent.rpc.AgentRpcClient;
import org.springframework.stereotype.Component;
import java.util.*;

/** Remote data adapter; Agent statistics belong to Python, with no Java SQL over its tables. */
@Component
public class AdminAgentMetricsMapper {
    private final AgentRpcClient rpc;
    public AdminAgentMetricsMapper(AgentRpcClient rpc) { this.rpc=rpc; }
    public List<Map<String,Object>> countStates(long actor,java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows(actor,"metric_states",start,end,source); }
    public List<Map<String,Object>> findMetrics(long actor,java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows(actor,"metric_rows",start,end,source); }
    public List<Map<String,Object>> countDaily(long actor,java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows(actor,"metric_daily",start,end,source); }
    public List<Map<String,Object>> findStages(long actor,java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows(actor,"metric_stages",start,end,source); }
}
