package com.easyjob.agent.rpc;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import com.easyjob.service.ArticleRevisionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnExpression("'${agent.internal-transport:${AGENT_INTERNAL_TRANSPORT:triple}}' == 'triple'")
public class TripleConfiguration {
    @Bean(initMethod="start", destroyMethod="close")
    public TripleRuntime tripleRuntime(AgentServiceAuth auth, AgentDraftService drafts, ArticleRevisionService revisions, ServiceCatalog catalog, com.easyjob.agent.service.AgentBlogQueryService queries,
            @Value("${agent.rpc.target:${AGENT_RPC_TARGET:127.0.0.1:50051}}") String target,
            @Value("${agent.rpc.bind:${BLOG_RPC_BIND:127.0.0.1}}") String bind,
            @Value("${agent.rpc.port:${BLOG_RPC_PORT:20881}}") int port) {
        var runtime=new TripleRuntime(new BlogRpcProvider(auth, drafts, revisions).queries(queries), target, bind, port);
        runtime.catalog(catalog); return runtime;
    }
    @Bean public AgentRpcClient agentRpcClient(TripleRuntime runtime, AgentServiceAuth auth) {
        return new AgentRpcClient(runtime.agent(), auth);
    }
}
