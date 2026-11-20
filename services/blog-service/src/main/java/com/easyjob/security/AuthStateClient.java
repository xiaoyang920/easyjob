package com.easyjob.security;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.*;
import java.util.List;
import java.util.Map;
@Component @ConditionalOnProperty(name="easyjob.auth.enabled",havingValue="true")
public class AuthStateClient {
    private final RestClient client;private final String key;
    public AuthStateClient(@Value("${easyjob.auth.base-url}")String url,@Value("${easyjob.auth.service-key}")String key){JdkClientHttpRequestFactory factory=new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build());factory.setReadTimeout(Duration.ofSeconds(2));client=RestClient.builder().baseUrl(url).requestFactory(factory).build();this.key=key;}
    public void require(IdentityTokens.Principal p){
        if(p==null||p.anonymous())throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.UNAUTHORIZED);
        try{client.post().uri("/internal/auth/session/check").header("X-Auth-Service-Key",key).body(Map.of("userId",p.userId(),"sid",p.sid(),"version",p.version())).retrieve().toBodilessEntity();}
        catch(org.springframework.web.client.HttpClientErrorException.Unauthorized invalid){throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.UNAUTHORIZED,"登录已失效");}
        catch(org.springframework.web.client.RestClientException unavailable){throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"认证服务暂不可用");}
    }
    @SuppressWarnings("unchecked")public Map<String,Boolean> batch(Collection<IdentityTokens.Principal> identities){List<Map<String,Object>> body=identities.stream().<Map<String,Object>>map(p->Map.of("userId",p.userId(),"sid",p.sid(),"version",p.version())).toList();Map<?,?> response=client.post().uri("/internal/auth/session/batch").header("X-Auth-Service-Key",key).body(body).retrieve().body(Map.class);if(response==null||!Integer.valueOf(200).equals(response.get("code"))||!(response.get("data")instanceof Map<?,?>))throw new IllegalStateException("Invalid session reply");return (Map<String,Boolean>)response.get("data");}
}
