package com.easyjob.security;
import com.nimbusds.jose.jwk.RSAKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import java.time.Instant;
import java.util.*;
import com.easyjob.security.IdentityTokens.Principal;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
@Component @ConditionalOnProperty(name="easyjob.auth.enabled",havingValue="true")
public class AgentDelegation {
    private final JwtEncoder encoder;private final String kid;
    public AgentDelegation(@Value("${easyjob.auth.blog-private-key-file}")String path){RSAKey key=IdentityTokens.key(path);encoder=IdentityTokens.encoder(key);kid=key.getKeyID();}
    public String issue(long userId){
        Principal p=RequestIdentity.get();if(p!=null&&!p.anonymous()){if(!p.userId().equals(Long.toString(userId)))throw new IllegalArgumentException("Identity mismatch");return IdentityTokens.issue(encoder,kid,"easyjob-blog","easyjob-agent","delegation",p,60,null,null,null);}
        Instant now=Instant.now();JwtClaimsSet claims=JwtClaimsSet.builder().issuer("easyjob-blog").audience(List.of("easyjob-agent")).issuedAt(now).notBefore(now.minusSeconds(1)).expiresAt(now.plusSeconds(60)).id(UUID.randomUUID().toString()).subject(Long.toString(userId)).claim("token_use","service_observe").build();
        return encoder.encode(JwtEncoderParameters.from(JwsHeader.with(SignatureAlgorithm.RS256).keyId(kid).build(),claims)).getTokenValue();
    }
}
