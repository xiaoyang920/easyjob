package com.easyjob.index;

import com.easyjob.discovery.NacosDiscovery;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.isA;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.spy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withForbiddenRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withNoContent;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class BlogIndexDiscoveryTests {
    private static final String KEY = "search-index-test-key-32-characters";
    private static final String NACOS = "http://localhost:8848/nacos/v3";
    private static final String INSTANCE = NACOS + "/client/ns/instance";
    private static final String SCOPE = "namespaceId=public&groupName=EASYJOB&serviceName=easyjob-blog";
    private static final String LIST = INSTANCE + "/list?" + SCOPE;
    private static final String OK = """
            {"code":0,"data":"ok"}
            """;
    private static final String COUNTS = """
            {"published":true,"likes":2,"collects":3}
            """;

    private final RestClient.Builder registryBuilder = mockableBuilder();
    private final MockRestServiceServer registry = MockRestServiceServer.bindTo(registryBuilder).build();
    private final NacosDiscovery nacos =
            new NacosDiscovery(registryBuilder, "http://localhost:8848", "public", "EASYJOB", "test", "a+b");

    @Test
    void renewsReregistersMissingInstanceAndDeregisters() {
        login("first");
        registry.expect(requestTo(INSTANCE)).andExpect(method(HttpMethod.POST))
                .andExpect(header("accessToken", "first"))
                .andExpect(content().string(containsString(SCOPE + "&ip=127.0.0.1&port=8080&ephemeral=true&heartBeat=false")))
                .andRespond(withSuccess(OK, MediaType.APPLICATION_JSON));
        registry.expect(requestTo(INSTANCE)).andExpect(method(HttpMethod.POST))
                .andExpect(content().string(containsString("heartBeat=true")))
                .andRespond(withSuccess("{\"code\":21003}", MediaType.APPLICATION_JSON));
        registry.expect(requestTo(INSTANCE)).andExpect(method(HttpMethod.POST))
                .andExpect(content().string(containsString("heartBeat=false")))
                .andRespond(withSuccess(OK, MediaType.APPLICATION_JSON));
        registry.expect(requestTo(INSTANCE + "?" + SCOPE + "&ip=127.0.0.1&port=8080&ephemeral=true"))
                .andExpect(method(HttpMethod.DELETE)).andExpect(header("accessToken", "first"))
                .andRespond(withSuccess(OK, MediaType.APPLICATION_JSON));

        nacos.registerOrRenew(NacosDiscovery.BLOG_SERVICE, "127.0.0.1", 8080, false);
        nacos.registerOrRenew(NacosDiscovery.BLOG_SERVICE, "127.0.0.1", 8080, true);
        nacos.deregister(NacosDiscovery.BLOG_SERVICE, "127.0.0.1", 8080);
        registry.verify();
    }

    @Test
    void resolvesOnlyEligibleInstancesAndRoutesBusinessRequestsWithOriginalServiceKey() {
        login("first");
        registry.expect(requestTo(LIST)).andExpect(header("accessToken", "first")).andRespond(withSuccess("""
                {"code":0,"data":[
                  {"ip":"127.0.0.1","port":8081,"healthy":true,"enabled":true,"weight":1},
                  {"ip":"127.0.0.1","port":8082,"healthy":false,"enabled":true,"weight":1},
                  {"ip":"127.0.0.1","port":8083,"healthy":true,"enabled":false,"weight":1},
                  {"ip":"127.0.0.1","port":8084,"healthy":true,"enabled":true,"weight":0},
                  {"ip":"127.0.0.1","port":8085,"healthy":true,"enabled":true,"weight":1}
                ]}
                """, MediaType.APPLICATION_JSON));
        RestClient.Builder businessBuilder = mockableBuilder();
        MockRestServiceServer business = MockRestServiceServer.bindTo(businessBuilder).build();
        business.expect(requestTo("http://127.0.0.1:8081/internal/search-index/articles/7/counts"))
                .andExpect(header("X-Search-Index-Key", KEY))
                .andRespond(withSuccess(COUNTS, MediaType.APPLICATION_JSON));
        business.expect(requestTo("http://127.0.0.1:8085/internal/search-index/jobs/job-7/complete?articleId=7"))
                .andExpect(method(HttpMethod.POST)).andExpect(header("X-Search-Index-Key", KEY))
                .andRespond(withNoContent());
        BlogIndexClient blog = blogClient(businessBuilder, nacos);

        assertThat(blog.counts(7).likes()).isEqualTo(2);
        blog.complete("job-7", 7);
        business.verify();
        registry.verify();
    }

    @Test
    void refreshesRejectedCredentialsAndReportsNoHealthyInstance() {
        login("first");
        registry.expect(requestTo(LIST)).andExpect(header("accessToken", "first"))
                .andRespond(withForbiddenRequest());
        login("second");
        registry.expect(requestTo(LIST)).andExpect(header("accessToken", "second"))
                .andRespond(withSuccess("{\"code\":0,\"data\":[]}", MediaType.APPLICATION_JSON));
        BlogIndexClient blog = blogClient(RestClient.builder(), nacos);

        assertThatThrownBy(() -> blog.counts(7)).isInstanceOf(IndexingException.class)
                .hasMessageContaining("no healthy easyjob-blog instance");
        registry.verify();
    }

    @Test
    void usesConfiguredDirectUrlWhenDiscoveryIsDisabled() {
        RestClient.Builder businessBuilder = mockableBuilder();
        MockRestServiceServer business = MockRestServiceServer.bindTo(businessBuilder).build();
        business.expect(requestTo("http://direct-blog:8080/internal/search-index/ready"))
                .andExpect(header("X-Search-Index-Key", KEY)).andRespond(withNoContent());

        blogClient(businessBuilder, null).checkReady();
        business.verify();
    }

    private void login(String token) {
        registry.expect(requestTo(NACOS + "/auth/user/login")).andExpect(method(HttpMethod.POST))
                .andExpect(content().string("username=test&password=a%2Bb"))
                .andRespond(withSuccess("{\"accessToken\":\"" + token + "\",\"tokenTtl\":18000}",
                        MediaType.APPLICATION_JSON));
    }

    private static BlogIndexClient blogClient(RestClient.Builder builder, NacosDiscovery discovery) {
        StaticListableBeanFactory factory = new StaticListableBeanFactory();
        if (discovery != null) {
            factory.addBean("nacos", discovery);
        }
        return new BlogIndexClient(builder, "http://direct-blog:8080", KEY,
                factory.getBeanProvider(NacosDiscovery.class));
    }

    private static RestClient.Builder mockableBuilder() {
        RestClient.Builder builder = spy(RestClient.builder());
        // Keep the mock server's factory in place when the client configures its timeouts.
        doReturn(builder).when(builder).requestFactory(isA(SimpleClientHttpRequestFactory.class));
        return builder;
    }
}
