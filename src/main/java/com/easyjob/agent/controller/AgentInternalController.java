package com.easyjob.agent.controller;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
public class AgentInternalController {
    private final AgentServiceAuth auth;
    private final AgentDraftService drafts;
    public AgentInternalController(AgentServiceAuth auth, AgentDraftService drafts) { this.auth = auth; this.drafts = drafts; }
    @PostMapping("/internal/agent/drafts")
    public Map<String,String> save(@RequestHeader(value="X-Agent-Key", required=false) String key,
        @RequestHeader(value="X-Agent-User", required=false) String user,
        @RequestBody AgentDraftService.DraftRequest request) {
        return drafts.save(auth.verify(key, user), request);
    }
}
