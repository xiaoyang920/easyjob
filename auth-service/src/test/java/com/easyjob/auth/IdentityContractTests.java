package com.easyjob.auth;
import com.easyjob.security.*;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import org.junit.jupiter.api.*;
import org.springframework.security.oauth2.jwt.*;
import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import com.nimbusds.jose.jwk.RSAKey;
import java.time.Instant;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
class IdentityContractTests {
    private static com.nimbusds.jose.jwk.RSAKey key;
    @BeforeAll static void setup()throws Exception{key=new RSAKeyGenerator(2048).keyID("test").generate();}
    IdentityTokens.Principal user(){return new IdentityTokens.Principal("7","a".repeat(64),3,List.of("1"));}
    String issue(String audience,String use,int seconds){return IdentityTokens.issue(IdentityTokens.encoder(key),"test","issuer",audience,use,user(),seconds,"GET","/api/one","trace");}
    @Test void signatureIssuerAudienceAndPurposeAreMandatory(){NimbusJwtDecoder decoder=IdentityTokens.decoder(key.toPublicJWK(),"issuer","blog",IdentityTokens.INTERNAL);String good=issue("blog",IdentityTokens.INTERNAL,15);assertEquals("7",IdentityTokens.forRequest(decoder,good,"GET","/api/one").userId());assertThrows(JwtException.class,()->decoder.decode(issue("agent",IdentityTokens.INTERNAL,15)));assertThrows(JwtException.class,()->decoder.decode(issue("blog",IdentityTokens.ACCESS,15)));assertThrows(JwtException.class,()->IdentityTokens.decoder(key,"other","blog",IdentityTokens.INTERNAL).decode(good));}
    @Test void externalTokenCannotMasqueradeAsInternal(){assertThrows(JwtException.class,()->IdentityTokens.decoder(key,"issuer","blog",IdentityTokens.INTERNAL).decode(issue("blog",IdentityTokens.ACCESS,1800)));}
    @Test void methodAndPathAreBound(){NimbusJwtDecoder decoder=IdentityTokens.decoder(key,"issuer","blog",IdentityTokens.INTERNAL);String token=issue("blog",IdentityTokens.INTERNAL,15);assertThrows(JwtException.class,()->IdentityTokens.forRequest(decoder,token,"POST","/api/one"));assertThrows(JwtException.class,()->IdentityTokens.forRequest(decoder,token,"GET","/api/two"));}
    @Test void expiryAndExcessiveLifetimeAreRejected(){NimbusJwtDecoder decoder=IdentityTokens.decoder(key,"issuer","blog",IdentityTokens.INTERNAL);Instant past=java.time.Instant.now().minusSeconds(120);JwtClaimsSet claims=JwtClaimsSet.builder().claims(values->values.putAll(decoder.decode(issue("blog",IdentityTokens.INTERNAL,15)).getClaims())).issuedAt(past).notBefore(past).expiresAt(past.plusSeconds(15)).build();String expired=IdentityTokens.encoder(key).encode(JwtEncoderParameters.from(JwsHeader.with(org.springframework.security.oauth2.jose.jws.SignatureAlgorithm.RS256).keyId("test").build(),claims)).getTokenValue();assertThrows(JwtException.class,()->decoder.decode(expired));assertThrows(JwtException.class,()->decoder.decode(issue("blog",IdentityTokens.INTERNAL,1800)));}
    @Test void anonymousAssertionsCannotAccessRequiredRoutes(){String token=IdentityTokens.issue(IdentityTokens.encoder(key),"test","issuer","blog",IdentityTokens.INTERNAL,IdentityTokens.Principal.guest(),15,"GET","/api/article/list","trace");assertTrue(IdentityTokens.forRequest(IdentityTokens.decoder(key,"issuer","blog",IdentityTokens.INTERNAL),token,"GET","/api/article/list").anonymous());assertEquals(RoutePolicy.Access.REQUIRED,RoutePolicy.access("POST","/api/article/create"));assertEquals(RoutePolicy.Access.OPTIONAL,RoutePolicy.access("GET","/api/article/list"));assertEquals(RoutePolicy.Access.REQUIRED,RoutePolicy.access("GET","/api/auth/future-admin"));}
    @Test void anotherSigningKeyCannotForgeIdentity()throws Exception{RSAKey other=new RSAKeyGenerator(2048).keyID("other").generate();assertThrows(JwtException.class,()->IdentityTokens.decoder(other,"issuer","blog",IdentityTokens.INTERNAL).decode(issue("blog",IdentityTokens.INTERNAL,15)));}
}
