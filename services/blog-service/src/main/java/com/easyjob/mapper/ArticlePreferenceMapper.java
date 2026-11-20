package com.easyjob.mapper;
import com.easyjob.agent.rpc.AgentRpcClient;
import org.springframework.stereotype.Component;
import java.util.*;

/** Profile data is read from its owner; no shared table access. */
@Component
public class ArticlePreferenceMapper {
    private final AgentRpcClient rpc;
    public ArticlePreferenceMapper(AgentRpcClient rpc) { this.rpc=rpc; }
    @SuppressWarnings("unchecked")
    public List<Map<String,Object>> findTopics(Long uid) {
        return (List<Map<String,Object>>)rpc.serviceQuery(uid,"profile_topics","","",1,20,"");
    }
}
