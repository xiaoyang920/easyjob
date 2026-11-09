package com.easyjob.security;

import com.nimbusds.jose.jwk.*;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.proc.SecurityContext;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import com.nimbusds.jose.jwk.RSAKey;
import org.springframework.security.oauth2.jwt.JwtClaimsSet.Builder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

/** Shared wire contract. Contains no account repository or business authorization. */
public final class IdentityTokens {
    public static final String HEADER="X-Easyjob-Identity";
    public static final String ACCESS="access", INTERNAL="gateway";
    private IdentityTokens() {}
    public record Principal(String userId,String sid,long version,List<String> roles) {
        public Principal { roles=List.copyOf(roles); }
        public boolean anonymous(){return userId==null;}
        public static Principal guest(){return new Principal(null,null,0,List.of());}
    }
    public static RSAKey key(String path) {
        try { RSAKey key=RSAKey.parse(Files.readString(Path.of(path)));if(key.size()<2048||key.getKeyID()==null)throw new IllegalArgumentException();return key; }
        catch(Exception error){throw new IllegalStateException("Invalid configured RSA key file");}
    }
    public static JwtEncoder encoder(RSAKey key) {
        if(!key.isPrivate())throw new IllegalArgumentException("Signing key must be private");
        return new NimbusJwtEncoder(new ImmutableJWKSet<SecurityContext>(new JWKSet(key)));
    }
    public static NimbusJwtDecoder decoder(RSAKey key,String issuer,String audience,String use) {
        try {
            NimbusJwtDecoder decoder=NimbusJwtDecoder.withPublicKey(key.toRSAPublicKey()).signatureAlgorithm(SignatureAlgorithm.RS256).build();
            decoder.setJwtValidator(validator(issuer,audience,use));return decoder;
        } catch(com.nimbusds.jose.JOSEException error){throw new IllegalStateException("Invalid verifier configuration");}
    }
    public static OAuth2TokenValidator<Jwt> validator(String issuer,String audience,String use) {
        return new DelegatingOAuth2TokenValidator<>(new JwtTimestampValidator(Duration.ofSeconds(use.equals(INTERNAL)?5:30)),new JwtIssuerValidator(issuer),jwt->{
            try {
                if(!jwt.getAudience().contains(audience)||!use.equals(jwt.getClaimAsString("token_use"))||jwt.getExpiresAt()==null||jwt.getIssuedAt()==null||jwt.getNotBefore()==null||jwt.getId()==null)throw new IllegalArgumentException();
                if(use.equals(INTERNAL)&&Duration.between(jwt.getIssuedAt(),jwt.getExpiresAt()).toSeconds()>20)throw new IllegalArgumentException();
                if(jwt.getIssuedAt().isAfter(Instant.now().plusSeconds(30)))throw new IllegalArgumentException();
                principal(jwt);return OAuth2TokenValidatorResult.success();
            } catch(RuntimeException invalid){return OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token"));}
        });
    }
    public static Principal principal(Jwt jwt) {
        if("anonymous".equals(jwt.getClaimAsString("kind"))) {
            if(!INTERNAL.equals(jwt.getClaimAsString("token_use"))||jwt.getSubject()!=null||jwt.hasClaim("sid"))throw new IllegalArgumentException("Invalid anonymous identity");
            return Principal.guest();
        }
        String uid=jwt.getSubject(),sid=jwt.getClaimAsString("sid");
        if(uid==null||!uid.matches("[1-9][0-9]{0,18}")||Long.parseLong(uid)<=0||sid==null||!sid.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Invalid identity");
        Object version=jwt.getClaim("ver");if(!(version instanceof Number n)||n.longValue()<0)throw new IllegalArgumentException("Invalid version");
        List<String> roles=jwt.getClaimAsStringList("roles");
        return new Principal(uid,sid,n.longValue(),roles==null?List.of():roles);
    }
    public static String issue(JwtEncoder encoder,String kid,String issuer,String audience,String use,Principal principal,int seconds,String method,String path,String trace) {
        Instant now=Instant.now();Builder claims=JwtClaimsSet.builder().issuer(issuer).audience(List.of(audience)).issuedAt(now).notBefore(now.minusSeconds(1)).expiresAt(now.plusSeconds(seconds)).id(UUID.randomUUID().toString()).claim("token_use",use);
        if(principal.anonymous())claims.claim("kind","anonymous");
        else claims.subject(principal.userId()).claim("kind","user").claim("sid",principal.sid()).claim("ver",principal.version()).claim("roles",principal.roles());
        if(method!=null)claims.claim("method",method).claim("path",path).claim("trace",trace);
        return encoder.encode(JwtEncoderParameters.from(JwsHeader.with(SignatureAlgorithm.RS256).keyId(kid).type("JWT").build(),claims.build())).getTokenValue();
    }
    public static Principal forRequest(JwtDecoder decoder,String token,String method,String path) {
        Jwt jwt=decoder.decode(token);
        if(!Objects.equals(method,jwt.getClaimAsString("method"))||!Objects.equals(path,jwt.getClaimAsString("path")))throw new JwtException("Wrong request binding");
        return principal(jwt);
    }
}
