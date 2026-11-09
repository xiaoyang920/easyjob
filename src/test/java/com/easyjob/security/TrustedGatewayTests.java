package com.easyjob.security;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.easyjob.security.IdentityTokens.Principal;
import com.nimbusds.jose.jwk.RSAKey;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
class TrustedGatewayTests {
    @TempDir Path folder;
    @Test void installsIdentityForRequestAndAlwaysClearsIt()throws Exception{
        RSAKey key=new RSAKeyGenerator(2048).keyID("test").generate();Path publicFile=folder.resolve("public.json");Files.writeString(publicFile,key.toPublicJWK().toJSONString());
        Principal p=new IdentityTokens.Principal("7","a".repeat(64),2,List.of("1"));String token=IdentityTokens.issue(IdentityTokens.encoder(key),"test","easyjob-gateway","easyjob-blog",IdentityTokens.INTERNAL,p,15,"GET","/api/agent/conversations","trace");
        MockHttpServletRequest request=new MockHttpServletRequest("GET","/api/agent/conversations");request.addHeader(IdentityTokens.HEADER,token);MockHttpServletResponse response=new MockHttpServletResponse();
        new TrustedGatewayFilter(publicFile.toString()).doFilter(request,response,(req,res)->{assertEquals(7L,com.easyjob.utils.UserContext.getUserId());assertEquals(p,RequestIdentity.get());});
        assertNull(RequestIdentity.get());assertNull(com.easyjob.utils.UserContext.getUserId());
    }
    @Test void forgedAndMissingContextNeverReachBusiness()throws Exception{
        RSAKey key=new RSAKeyGenerator(2048).keyID("test").generate();Path publicFile=folder.resolve("public.json");Files.writeString(publicFile,key.toPublicJWK().toJSONString());
        MockHttpServletRequest request=new MockHttpServletRequest("GET","/api/agent/conversations");request.addHeader("X-User-Id","1");MockHttpServletResponse response=new MockHttpServletResponse();new TrustedGatewayFilter(publicFile.toString()).doFilter(request,response,(req,res)->fail("Must reject direct caller"));assertEquals(401,response.getStatus());
    }
    @Test void stateFailureClosesExistingConnection()throws Exception{
        AuthStateClient auth=mock(AuthStateClient.class);when(auth.batch(any())).thenThrow(new IllegalStateException("offline"));ConnectionSessions monitor=new ConnectionSessions(auth,new ObjectMapper());
        AtomicBoolean closed=new java.util.concurrent.atomic.AtomicBoolean();AutoCloseable registration=ConnectionSessions.register(new IdentityTokens.Principal("7","a".repeat(64),2,List.of("1")),()->closed.set(true));
        monitor.check();assertTrue(closed.get());registration.close();monitor.stop();
    }
}
