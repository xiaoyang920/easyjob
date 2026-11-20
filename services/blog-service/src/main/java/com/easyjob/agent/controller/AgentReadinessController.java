package com.easyjob.agent.controller;

import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.agent.security.AgentServiceAuth;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import java.util.Map;

/** Service-key-only probe of the same Java -> Agent connection used by requests. */
@RestController
public class AgentReadinessController {
    private final AgentServiceAuth auth;
    private final AgentRpcClient agent;

    public AgentReadinessController(AgentServiceAuth auth, AgentRpcClient agent) {
        this.auth = auth;
        this.agent = agent;
    }

    @GetMapping("/internal/agent/ready")
    public Map<String, String> ready(@RequestHeader(value="X-Agent-Key", required=false) String key) {
        long probeUser = auth.verify(key, "1");
        // Read-only, no admission lease or LLM. Discard the result: no user data
        // is exposed, and this can run while the restart admission lock is held.
        agent.serviceQuery(probeUser,"health","","",1,1,"");
        return Map.of("status", "ready", "rpc", "ok");
    }
}
