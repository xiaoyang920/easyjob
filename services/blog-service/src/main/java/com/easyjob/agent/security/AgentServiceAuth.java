package com.easyjob.agent.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import com.easyjob.rpc.v1.Identity.Builder;
import java.util.List;
import java.util.Map;

/** Dedicated service identity; public JWTs never grant access to internal APIs. */
@Component
public class AgentServiceAuth {
    @org.springframework.beans.factory.annotation.Autowired(required=false)private com.easyjob.security.AgentDelegation delegation;
    @org.springframework.beans.factory.annotation.Autowired(required=false)private com.easyjob.security.AuthStateClient sessions;
    @org.springframework.beans.factory.annotation.Autowired(required=false)private com.easyjob.mapper.AgentRunMapper mapper;
    private final String key;
    public AgentServiceAuth(@Value("${AGENT_SERVICE_KEY:}") String key) { this.key = key; }
    public HttpHeaders headers(Long userId) {
        if (key.getBytes(StandardCharsets.UTF_8).length < 32 || userId == null || userId <= 0) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Agent service identity is not configured");
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Agent-Key", key);
        headers.set("X-Agent-User", userId.toString());
        if(delegation!=null)headers.set("X-Agent-Delegation",delegation.issue(userId));
        return headers;
    }
    public long verify(String suppliedKey, String suppliedUser) {
        if (key.getBytes(StandardCharsets.UTF_8).length < 32) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
        if (suppliedKey == null || !MessageDigest.isEqual(key.getBytes(StandardCharsets.UTF_8), suppliedKey.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        }
        try {
            long userId = Long.parseLong(suppliedUser);
            if (userId <= 0) throw new NumberFormatException();
            return userId;
        } catch (RuntimeException e) { throw new ResponseStatusException(HttpStatus.UNAUTHORIZED); }
    }
    public com.easyjob.rpc.v1.Identity identity(Long userId) {
        headers(userId); // Same fail-closed identity rules as the compatibility HTTP transport.
        Builder builder=com.easyjob.rpc.v1.Identity.newBuilder().setUserId(userId).setServiceKey(key).setTraceId(com.easyjob.observability.RequestTrace.current());
        if(delegation!=null)builder.setDelegationToken(delegation.issue(userId));
        return builder.build();
    }
    public long delegated(com.easyjob.rpc.v1.Identity identity,String runId,String executionToken){
        long uid=verify(identity.getServiceKey(),Long.toString(identity.getUserId()));if(sessions==null)return uid;
        String sid=identity.getAuthSessionId();long version=identity.getAuthVersion();
        if(runId!=null&&!runId.isBlank()){
            List<Map<String, Object>> rows=mapper.findRun(runId, uid);
            if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.FORBIDDEN);
            Map<String, Object> row=rows.getFirst();sid=(String)row.get("auth_sid");if(sid==null||row.get("auth_version")==null)throw new ResponseStatusException(HttpStatus.FORBIDDEN,"运行尚未取得当前会话授权");version=((Number)row.get("auth_version")).longValue();
            if(executionToken!=null&&!executionToken.isBlank()&&!executionToken.equals(row.get("execution_token")))throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        }
        sessions.require(new com.easyjob.security.IdentityTokens.Principal(Long.toString(uid),sid,version,java.util.List.of()));return uid;
    }
}
