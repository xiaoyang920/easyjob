package com.easyjob.agent.security;

import com.easyjob.agent.service.AgentDraftService.DraftRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

/** A save permission reserved durably by the Agent before Java's local transaction. */
@Component
public class DraftSavePermit {
    private final AgentServiceAuth auth;
    private final ObjectMapper json;
    public DraftSavePermit(AgentServiceAuth auth,ObjectMapper json) { this.auth=auth;this.json=json; }
    public void verify(long uid,DraftRequest d) {
        try {
            String[] parts=d.savePermit().split("\\.");
            if(parts.length!=2) throw new IllegalArgumentException();
            var mac=javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(auth.identity(uid).getServiceKey().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
            if(!MessageDigest.isEqual(mac.doFinal(parts[0].getBytes(StandardCharsets.US_ASCII)),Base64.getUrlDecoder().decode(parts[1]))) throw new IllegalArgumentException();
            var claims=json.readTree(Base64.getUrlDecoder().decode(parts[0]));
            long now=java.time.Instant.now().getEpochSecond(),exp=claims.path("exp").asLong();
            if(exp<now || exp>now+125 || claims.path("uid").asLong()!=uid || claims.path("aid").asLong()!=d.articleId()
                || !claims.path("rid").asText().equals(d.runId()) || !claims.path("hash").asText().equals(d.draftHash())
                || !claims.path("revision").asText("").equals(d.expectedRevisionId()==null?"":d.expectedRevisionId())
                || !claims.path("lock").asText("").equals(d.expectedLockVersion()==null?"":d.expectedLockVersion().toString())) throw new IllegalArgumentException();
        } catch(Exception e) { throw new ResponseStatusException(HttpStatus.CONFLICT,"Draft save permission expired or invalid"); }
    }
}
