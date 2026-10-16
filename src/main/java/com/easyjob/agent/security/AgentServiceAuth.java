package com.easyjob.agent.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Dedicated service identity; public JWTs never grant access to internal APIs. */
@Component
public class AgentServiceAuth {
    private final String key;
    public AgentServiceAuth(@Value("${AGENT_SERVICE_KEY:}") String key) { this.key = key; }
    public HttpHeaders headers(Long userId) {
        if (key.getBytes(StandardCharsets.UTF_8).length < 32 || userId == null || userId <= 0) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Agent service identity is not configured");
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Agent-Key", key);
        headers.set("X-Agent-User", userId.toString());
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
        return com.easyjob.rpc.v1.Identity.newBuilder().setUserId(userId).setServiceKey(key)
            .setTraceId(com.easyjob.observability.RequestTrace.current()).build();
    }
}
