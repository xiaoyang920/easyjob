package com.easyjob.gateway;
import com.easyjob.security.*;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.http.HttpStatus;
import reactor.core.publisher.*;
import java.nio.file.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.nimbusds.jose.jwk.RSAKey;
import java.util.concurrent.atomic.AtomicBoolean;
class UnifiedIdentityTests {
    @TempDir Path temp;
    @SuppressWarnings("unchecked")UnifiedIdentityFilter filter()throws Exception{RSAKey key=new RSAKeyGenerator(2048).keyID("test").generate();Path file=temp.resolve("key.json");Files.writeString(file,key.toJSONString());ReactiveStringRedisTemplate redis=mock(ReactiveStringRedisTemplate.class);when(redis.execute(any(),anyList(),anyList())).thenReturn(Flux.just(1L));return new UnifiedIdentityFilter(redis,"http://127.0.0.1:1","http://127.0.0.1:1/jwks","issuer",file.toString(),"s".repeat(48),300,20,12);}
    @Test void missingCredentialIsRejectedBeforeBusiness()throws Exception{MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/article/create"));filter().filter(exchange,e->{fail("Business must not execute");return Mono.empty();}).block();assertEquals(HttpStatus.UNAUTHORIZED,exchange.getResponse().getStatusCode());}
    @Test void anonymousReadGetsSignedContextAndForgedHeadersAreRemoved()throws Exception{MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list").header("X-User-Id","1").header("X-Easyjob-Identity","forged").header("X-Auth-Service-Key","forged"));filter().filter(exchange,e->{assertNull(e.getRequest().getHeaders().getFirst("X-User-Id"));assertNull(e.getRequest().getHeaders().getFirst("X-Auth-Service-Key"));assertNotEquals("forged",e.getRequest().getHeaders().getFirst(IdentityTokens.HEADER));return Mono.empty();}).block();}
    @Test void invalidOptionalCredentialDoesNotBecomeAnonymous()throws Exception{MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list").header("Authorization","Bearer broken"));filter().filter(exchange,e->{fail("Invalid optional identity must not pass");return Mono.empty();}).block();assertEquals(HttpStatus.UNAUTHORIZED,exchange.getResponse().getStatusCode());}
    @Test void refreshIgnoresExpiredAccessAndKeepsCsrfMarkerAndCookie()throws Exception{MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.post("/api/auth/refresh").header("Authorization","Bearer expired").header("X-Auth-Refresh","1").header("Cookie","easyjob_refresh=opaque"));filter().filter(exchange,e->{assertEquals("1",e.getRequest().getHeaders().getFirst("X-Auth-Refresh"));assertEquals("easyjob_refresh=opaque",e.getRequest().getHeaders().getFirst("Cookie"));assertNull(e.getRequest().getHeaders().getFirst("Authorization"));return Mono.empty();}).block();}
    @Test void downstreamErrorIsNotRewrittenAsAuthenticationFailure()throws Exception{UnifiedIdentityFilter filter=filter();MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list"));assertThrows(IllegalStateException.class,()->filter.filter(exchange,e->Mono.error(new IllegalStateException("business failure"))).block());}
    @Test void encodedSearchQueryIsPreserved()throws Exception{MockServerWebExchange exchange=MockServerWebExchange.from(MockServerHttpRequest.get("/api/search?keyword=%E6%B5%8B%E8%AF%95"));filter().filter(exchange,e->{assertEquals(exchange.getRequest().getURI().getRawQuery(),e.getRequest().getURI().getRawQuery());return Mono.empty();}).block();}
    @Test void authFailureDoesNotOpenArticleCircuit(){AvailabilityFilter filter=new AvailabilityFilter();for(int i=0;i<12;i++)filter.filter(MockServerWebExchange.from(MockServerHttpRequest.post("/api/auth/login")),e->Mono.error(new IllegalStateException("auth offline"))).block();AtomicBoolean called=new java.util.concurrent.atomic.AtomicBoolean();filter.filter(MockServerWebExchange.from(MockServerHttpRequest.get("/api/article/list")),e->{called.set(true);return Mono.empty();}).block();assertTrue(called.get());}
}
