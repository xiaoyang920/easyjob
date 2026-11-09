package com.easyjob.gateway;

import com.easyjob.security.*;
import com.easyjob.security.IdentityTokens.Principal;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.cloud.gateway.filter.*;
import org.springframework.core.Ordered;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.time.Duration;
import java.util.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import com.easyjob.security.RoutePolicy.Access;
import com.nimbusds.jose.jwk.RSAKey;
import java.net.URI;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;

/** External credential validation, online session admission and signed identity propagation. */
@Component @ConditionalOnProperty(name="easyjob.auth.enabled",havingValue="true")
public class UnifiedIdentityFilter implements GlobalFilter,Ordered {
    private static final DefaultRedisScript<Long> LIMIT=new DefaultRedisScript<>("local n=redis.call('INCR',KEYS[1]);if n==1 then redis.call('EXPIRE',KEYS[1],60) end;if n>tonumber(ARGV[1]) then return 0 end;return 1",Long.class);
    private final ReactiveJwtDecoder access;private final JwtEncoder signing;private final String kid,serviceKey;private final WebClient auth;private final ReactiveStringRedisTemplate redis;
    private final int apiLimit,authLimit,aiLimit;
    static class Rejected extends RuntimeException{final HttpStatus status;Rejected(HttpStatus status){this.status=status;}}
    public record SessionReply(int code,Principal data){}
    public UnifiedIdentityFilter(ReactiveStringRedisTemplate redis,@Value("${easyjob.auth.base-url}")String base,@Value("${easyjob.auth.jwks-uri}")String jwks,@Value("${easyjob.auth.issuer:easyjob-auth}")String issuer,@Value("${easyjob.auth.gateway-private-key-file}")String file,@Value("${easyjob.auth.service-key}")String serviceKey,
            @Value("${easyjob.gateway.api-per-minute:300}")int api,@Value("${easyjob.gateway.auth-per-minute:20}")int login,@Value("${easyjob.gateway.ai-per-minute:12}")int ai){
        AtomicLong nextKeyFetch=new java.util.concurrent.atomic.AtomicLong();
        NimbusReactiveJwtDecoder decoder=NimbusReactiveJwtDecoder.withJwkSetUri(jwks).jwsAlgorithm(SignatureAlgorithm.RS256).webClient(WebClient.builder().filter((req,next)->Mono.defer(()->{long now=System.currentTimeMillis(),allowed=nextKeyFetch.get();if(now<allowed||!nextKeyFetch.compareAndSet(allowed,now+2000))return Mono.error(new IllegalStateException("JWK refresh cooldown"));return next.exchange(req).timeout(Duration.ofSeconds(2));})).build()).build();
        decoder.setJwtValidator(IdentityTokens.validator(issuer,"easyjob-api",IdentityTokens.ACCESS));access=decoder;
        RSAKey key=IdentityTokens.key(file);signing=IdentityTokens.encoder(key);kid=key.getKeyID();this.redis=redis;this.serviceKey=serviceKey;auth=WebClient.builder().baseUrl(base).build();apiLimit=api;authLimit=login;aiLimit=ai;
        if(serviceKey.getBytes(StandardCharsets.UTF_8).length<32)throw new IllegalStateException("Auth service identity missing");
    }
    @Override public int getOrder(){return -200;}
    @Override public Mono<Void> filter(ServerWebExchange original,GatewayFilterChain chain){
        String path=original.getRequest().getPath().value(),method=original.getRequest().getMethod().name(),trace=UUID.randomUUID().toString();
        if(RoutePolicy.access(method,path)==RoutePolicy.Access.INTERNAL)return EdgeFilter.reject(original,HttpStatus.NOT_FOUND,"接口不存在");
        ServerHttpRequest clean=original.getRequest().mutate().headers(headers->{headers.keySet().removeIf(n->{String lower=n.toLowerCase(Locale.ROOT);return lower.startsWith("x-agent-")||lower.startsWith("x-easyjob-")||lower.startsWith("x-auth-")||lower.startsWith("x-forwarded-")||Set.of("x-user-id","x-service-key","x-gateway-user","forwarded").contains(lower);});
            // Only this CSRF marker is part of the public browser protocol.
            if("1".equals(original.getRequest().getHeaders().getFirst("X-Auth-Refresh")))headers.set("X-Auth-Refresh","1");headers.set("X-Request-Id",trace);
        }).build();
        ServerWebExchange exchange=original.mutate().request(clean).build();exchange.getResponse().getHeaders().set("X-Request-Id",trace);
        String ip=original.getRequest().getRemoteAddress()==null?"unknown":original.getRequest().getRemoteAddress().getAddress().getHostAddress();
        Mono<Principal> admission=limit("ingress","ip:"+ip,Math.max(apiLimit*3,authLimit)).then(identity(original,method,path));
        Mono<ServerWebExchange> prepared=admission.flatMap(p->{
            String owner=p.anonymous()?"ip:"+ip:"user:"+p.userId();
            boolean observe="GET".equals(method)&&(path.equals("/api/agent/run-overview")||path.equals("/api/notification/unread-count")||path.equals("/api/chat/total-unread-count")||path.matches("/api/agent/runs/[^/]+")||path.matches("/api/agent/conversations/[^/]+/run"));
            String bucket=RoutePolicy.authRoute(path)?"auth":path.equals("/api/notification/stream")?"stream":observe?"observe":"api";
            int maximum=bucket.equals("auth")?authLimit:bucket.equals("stream")?30:apiLimit;
            Mono<Void> allowed=limit(bucket,owner,maximum);
            if(path.matches("/api/agent/chat(/stream|/resume|/resume/stream)?"))allowed=allowed.then(limit("ai",owner,aiLimit));
            return allowed.then(Mono.fromSupplier(()->{
                String token=IdentityTokens.issue(signing,kid,"easyjob-gateway",RoutePolicy.audience(path),IdentityTokens.INTERNAL,p,15,method,path,trace);
                ServerHttpRequest request=clean.mutate().headers(headers->{headers.remove("Authorization");headers.set(IdentityTokens.HEADER,token);}).build();
                // Remove query bearer credentials before forwarding, including WebSocket/SSE.
                if(request.getQueryParams().containsKey("token")){
                    String raw=Arrays.stream(request.getURI().getRawQuery().split("&")).filter(part->!"token".equals(java.net.URLDecoder.decode(part.split("=",2)[0],StandardCharsets.UTF_8))).collect(java.util.stream.Collectors.joining("&"));
                    URI uri=org.springframework.web.util.UriComponentsBuilder.fromUri(request.getURI()).replaceQuery(raw.isEmpty()?null:raw).build(true).toUri();request=request.mutate().uri(uri).build();
                }
                return exchange.mutate().request(request).build();
            }));
        });
        // Only admission errors are mapped here. Downstream errors belong to downstream handling.
        return prepared.onErrorResume(error->{HttpStatus status=error instanceof Rejected r?r.status:HttpStatus.SERVICE_UNAVAILABLE;
            String message=status==HttpStatus.UNAUTHORIZED?"登录已过期，请重新登录":status==HttpStatus.TOO_MANY_REQUESTS?"请求过于频繁，请稍后重试":"认证服务暂不可用，请稍后重试";
            return EdgeFilter.reject(exchange,status,message).then(Mono.empty());
        }).flatMap(chain::filter);
    }
    private Mono<Principal> identity(ServerWebExchange exchange,String method,String path){
        Access policy=RoutePolicy.access(method,path);if(policy==RoutePolicy.Access.PUBLIC)return Mono.just(Principal.guest());
        List<String> values=exchange.getRequest().getHeaders().getOrEmpty("Authorization");if(values.size()>1)return Mono.error(new Rejected(HttpStatus.UNAUTHORIZED));
        String token=values.isEmpty()?null:values.getFirst();if(token!=null){if(!token.startsWith("Bearer "))return Mono.error(new Rejected(HttpStatus.UNAUTHORIZED));token=token.substring(7);}
        if(token==null&&(path.startsWith("/ws")||path.startsWith("/api/agent/")||path.equals("/api/notification/stream")))token=exchange.getRequest().getQueryParams().getFirst("token");
        if(token==null)return policy==RoutePolicy.Access.OPTIONAL?Mono.just(Principal.guest()):Mono.error(new Rejected(HttpStatus.UNAUTHORIZED));
        return access.decode(token).onErrorMap(error->new Rejected(error instanceof BadJwtException?HttpStatus.UNAUTHORIZED:HttpStatus.SERVICE_UNAVAILABLE)).map(IdentityTokens::principal).flatMap(this::session);
    }
    private Mono<Principal> session(Principal asserted){
        return auth.post().uri("/internal/auth/session/check").header("X-Auth-Service-Key",serviceKey).bodyValue(Map.of("userId",asserted.userId(),"sid",asserted.sid(),"version",asserted.version())).exchangeToMono(response->{
            if(response.statusCode().value()==401)return Mono.error(new Rejected(HttpStatus.UNAUTHORIZED));
            if(!response.statusCode().is2xxSuccessful())return Mono.error(new Rejected(HttpStatus.SERVICE_UNAVAILABLE));return response.bodyToMono(SessionReply.class);
        }).timeout(Duration.ofSeconds(2)).switchIfEmpty(Mono.error(new Rejected(HttpStatus.SERVICE_UNAVAILABLE))).map(reply->{
            Principal p=reply.data();if(reply.code()!=200||p==null||!Objects.equals(p.userId(),asserted.userId())||!Objects.equals(p.sid(),asserted.sid())||p.version()!=asserted.version())throw new Rejected(HttpStatus.SERVICE_UNAVAILABLE);return p;
        });
    }
    private Mono<Void> limit(String bucket,String principal,int maximum){
        String digest;try{digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(principal.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){return Mono.error(error);}
        return redis.execute(LIMIT,List.of("gateway:limit:"+bucket+":"+digest),List.of(Integer.toString(maximum))).next().switchIfEmpty(Mono.error(new Rejected(HttpStatus.SERVICE_UNAVAILABLE))).flatMap(n->n==1?Mono.empty():Mono.error(new Rejected(HttpStatus.TOO_MANY_REQUESTS)));
    }
}
