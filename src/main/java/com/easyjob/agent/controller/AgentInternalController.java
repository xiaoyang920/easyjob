package com.easyjob.agent.controller;

import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.agent.service.AgentDraftService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
import java.util.List;
import com.easyjob.service.ArticleRevisionService;

@RestController
public class AgentInternalController {
    private final AgentServiceAuth auth;
    private final AgentDraftService drafts;
    private final ArticleRevisionService revisions;
    public AgentInternalController(AgentServiceAuth auth, AgentDraftService drafts,ArticleRevisionService revisions) { this.auth = auth; this.drafts = drafts; this.revisions=revisions; }
    @ExceptionHandler(com.easyjob.exception.BusinessException.class)
    public org.springframework.http.ResponseEntity<Map<String,Object>> businessError(com.easyjob.exception.BusinessException error) {
        return org.springframework.http.ResponseEntity.status(error.getCode()).body(Map.of("code",error.getCode(),"message",error.getMessage()));
    }
    @GetMapping("/internal/agent/drafts")
    public List<Map<String,Object>> list(@RequestHeader(value="X-Agent-Key",required=false) String key,
        @RequestHeader(value="X-Agent-User",required=false) String user,@RequestParam(defaultValue="") String keyword) {
        return revisions.ownDrafts(auth.verify(key,user),keyword);
    }
    @GetMapping("/internal/agent/drafts/{articleId}")
    public Map<String,Object> read(@RequestHeader(value="X-Agent-Key",required=false) String key,
        @RequestHeader(value="X-Agent-User",required=false) String user,@PathVariable long articleId) {
        return revisions.ownDraft(auth.verify(key,user),articleId);
    }
    @PostMapping("/internal/agent/drafts")
    public Map<String,String> save(@RequestHeader(value="X-Agent-Key", required=false) String key,
        @RequestHeader(value="X-Agent-User", required=false) String user,
        @RequestBody AgentDraftService.DraftRequest request) {
        return drafts.save(auth.verify(key, user), request);
    }
}
