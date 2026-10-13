package com.easyjob.mapper;
import com.easyjob.agent.rpc.AgentRpcClient;
import org.springframework.stereotype.Component;
import java.util.*;

/** Remote data adapter; Agent statistics belong to Python, with no Java SQL over its tables. */
@Component
public class AdminAgentMetricsMapper {
    private final AgentRpcClient rpc;
    public AdminAgentMetricsMapper(AgentRpcClient rpc) { this.rpc=rpc; }
    public List<Map<String,Object>> countStates(java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows("metric_states",start,end,source); }
    public List<Map<String,Object>> findMetrics(java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows("metric_rows",start,end,source); }
    public List<Map<String,Object>> countDaily(java.sql.Timestamp start,java.sql.Timestamp end,String source) { return rpc.serviceRows("metric_daily",start,end,source); }
}
