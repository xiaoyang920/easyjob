package com.easyjob.discovery;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.util.UriBuilder;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

@Component
@ConditionalOnProperty(name = "easyjob.nacos.enabled", havingValue = "true")
public class NacosDiscovery {
    public static final String BLOG_SERVICE = "easyjob-blog";

    private static final String INSTANCE_PATH = "/nacos/v3/client/ns/instance";
    private final RestClient client;
    private final String namespace;
    private final String group;
    private final String username;
    private final String password;
    private Token token;

    public NacosDiscovery(RestClient.Builder builder,
                          @Value("${easyjob.nacos.server-url:http://127.0.0.1:8848}") String serverUrl,
                          @Value("${easyjob.nacos.namespace:public}") String namespace,
                          @Value("${easyjob.nacos.group:EASYJOB}") String group,
                          @Value("${easyjob.nacos.username:nacos}") String username,
                          @Value("${easyjob.nacos.password:}") String password) {
        if (username.isBlank() || password.isBlank()) {
            throw new IllegalArgumentException("Nacos requires EASYJOB_NACOS_USERNAME and EASYJOB_NACOS_PASSWORD");
        }
        SimpleClientHttpRequestFactory requests = new SimpleClientHttpRequestFactory();
        requests.setConnectTimeout(Duration.ofSeconds(2));
        requests.setReadTimeout(Duration.ofSeconds(2));
        this.client = builder.baseUrl(serverUrl).requestFactory(requests).build();
        this.namespace = namespace;
        this.group = group;
        this.username = username;
        this.password = password;
    }

    public void registerOrRenew(String service, String ip, int port, boolean heartbeat) {
        JsonNode response = publish(service, ip, port, heartbeat);
        if (heartbeat && response.path("code").asInt(-1) == 21003) {
            response = publish(service, ip, port, false);
        }
        if (!"ok".equals(data(response).asText())) {
            throw new IllegalStateException("Nacos did not confirm instance registration");
        }
    }

    private JsonNode publish(String service, String ip, int port, boolean heartbeat) {
        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("namespaceId", namespace);
        form.add("groupName", group);
        form.add("serviceName", service);
        form.add("ip", ip);
        form.add("port", Integer.toString(port));
        form.add("ephemeral", "true");
        form.add("heartBeat", Boolean.toString(heartbeat));
        return authenticated(accessToken -> client.post().uri(INSTANCE_PATH)
                .header("accessToken", accessToken).contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form).retrieve().body(JsonNode.class));
    }

    public void deregister(String service, String ip, int port) {
        data(authenticated(accessToken -> client.delete()
                .uri(builder -> serviceQuery(builder.path(INSTANCE_PATH), service)
                        .queryParam("ip", ip).queryParam("port", port)
                        .queryParam("ephemeral", true).build())
                .header("accessToken", accessToken).retrieve().body(JsonNode.class)));
    }

    public List<URI> healthyInstances(String service) {
        JsonNode instances = data(authenticated(accessToken -> client.get()
                .uri(builder -> serviceQuery(builder.path(INSTANCE_PATH + "/list"), service).build())
                .header("accessToken", accessToken).retrieve().body(JsonNode.class)));
        if (!instances.isArray()) {
            throw new IllegalStateException("Nacos did not return an instance list");
        }
        List<URI> endpoints = new ArrayList<>();
        for (JsonNode instance : instances) {
            if (instance.path("healthy").asBoolean() && instance.path("enabled").asBoolean()
                    && instance.path("weight").asDouble() > 0) {
                endpoints.add(endpoint(instance));
            }
        }
        return List.copyOf(endpoints);
    }

    private UriBuilder serviceQuery(UriBuilder builder, String service) {
        return builder.queryParam("namespaceId", namespace).queryParam("groupName", group)
                .queryParam("serviceName", service);
    }

    private static URI endpoint(JsonNode instance) {
        String ip = instance.path("ip").asText();
        int port = instance.path("port").asInt();
        if (ip.isBlank() || port < 1 || port > 65535) {
            throw new IllegalStateException("Nacos returned an invalid instance address");
        }
        try {
            return new URI("http", null, ip, port, null, null, null);
        } catch (URISyntaxException exception) {
            throw new IllegalStateException("Nacos returned an invalid instance address");
        }
    }

    private JsonNode authenticated(Function<String, JsonNode> request) {
        Token current = accessToken(null);
        try {
            return requireResponse(request.apply(current.value()));
        } catch (RestClientResponseException exception) {
            HttpStatusCode status = exception.getStatusCode();
            if (status.value() != 401 && status.value() != 403) {
                throw exception;
            }
            return requireResponse(request.apply(accessToken(current).value()));
        }
    }

    private synchronized Token accessToken(Token rejected) {
        if (token == null || token == rejected || System.nanoTime() - token.refreshAt() >= 0) {
            MultiValueMap<String, String> credentials = new LinkedMultiValueMap<>();
            credentials.add("username", username);
            credentials.add("password", password);
            JsonNode result = requireResponse(client.post().uri("/nacos/v3/auth/user/login")
                    .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                    .body(credentials).retrieve().body(JsonNode.class));
            String value = result.path("accessToken").asText();
            int ttl = result.path("tokenTtl").asInt();
            if (value.isBlank() || ttl <= 0) {
                throw new IllegalStateException("Nacos did not return a usable access token");
            }
            token = new Token(value, System.nanoTime() + Duration.ofSeconds(ttl - Math.min(30, ttl / 2)).toNanos());
        }
        return token;
    }

    private static JsonNode requireResponse(JsonNode response) {
        if (response == null) {
            throw new IllegalStateException("Nacos returned an empty response");
        }
        return response;
    }

    private static JsonNode data(JsonNode response) {
        int code = response.path("code").asInt(-1);
        if (code != 0) {
            throw new IllegalStateException("Nacos request failed with code " + code);
        }
        return response.path("data");
    }

    private record Token(String value, long refreshAt) {
    }
}
