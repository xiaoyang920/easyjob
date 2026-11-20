package com.easyjob.index;

import com.easyjob.discovery.NacosDiscovery;
import com.easyjob.dto.ArticleIndexSnapshot;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

@Component
public class BlogIndexClient {
    private final RestClient blog;
    private final String directUrl;
    private final NacosDiscovery nacos;
    private List<URI> instances;
    private long refreshAt;
    private int nextInstance;

    public BlogIndexClient(RestClient.Builder builder,
                           @Value("${search-index.blog-url}") String baseUrl,
                           @Value("${SEARCH_INDEX_SERVICE_KEY:}") String key,
                           ObjectProvider<NacosDiscovery> discovery) {
        if (key.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalArgumentException("SEARCH_INDEX_SERVICE_KEY must contain at least 32 bytes");
        }
        SimpleClientHttpRequestFactory requests = new SimpleClientHttpRequestFactory();
        requests.setConnectTimeout(Duration.ofSeconds(2));
        requests.setReadTimeout(Duration.ofSeconds(10));
        blog = builder.requestFactory(requests).defaultHeader("X-Search-Index-Key", key).build();
        directUrl = baseUrl.replaceFirst("/+$", "");
        nacos = discovery.getIfAvailable();
    }

    public ArticleIndexSnapshot snapshot(long articleId) {
        return required(blog.get().uri(endpoint() + "/internal/search-index/articles/{id}", articleId)
                .retrieve().body(ArticleIndexSnapshot.class));
    }

    public ArticleIndexSnapshot.Counts counts(long articleId) {
        return required(blog.get().uri(endpoint() + "/internal/search-index/articles/{id}/counts", articleId)
                .retrieve().body(ArticleIndexSnapshot.Counts.class));
    }

    public boolean completed(String jobId, long articleId) {
        return required(blog.get().uri(endpoint() + "/internal/search-index/jobs/{id}?articleId={articleId}", jobId, articleId)
                .retrieve().body(ArticleIndexSnapshot.JobState.class)).completed();
    }

    public void complete(String jobId, long articleId) {
        requireNoContent(blog.post().uri(endpoint() + "/internal/search-index/jobs/{id}/complete?articleId={articleId}", jobId, articleId)
                .retrieve().toBodilessEntity());
    }

    public void checkReady() {
        // Blog and the registry may finish startup in either order.
        long deadline = System.nanoTime() + Duration.ofSeconds(20).toNanos();
        while (true) {
            try {
                requireNoContent(blog.get().uri(endpoint() + "/internal/search-index/ready").retrieve().toBodilessEntity());
                return;
            } catch (RestClientException | IndexingException | IllegalStateException exception) {
                if (nacos == null || System.nanoTime() - deadline >= 0) {
                    throw exception;
                }
                try {
                    Thread.sleep(Duration.ofSeconds(1));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("Interrupted while waiting for Blog", interrupted);
                }
            }
        }
    }

    private String endpoint() {
        return nacos == null ? directUrl : discoveredEndpoint().toString();
    }

    private synchronized URI discoveredEndpoint() {
        if (instances == null || System.nanoTime() - refreshAt >= 0) {
            instances = nacos.healthyInstances(NacosDiscovery.BLOG_SERVICE);
            refreshAt = System.nanoTime() + Duration.ofSeconds(3).toNanos();
        }
        if (instances.isEmpty()) {
            throw new IndexingException("Nacos has no healthy easyjob-blog instance");
        }
        return instances.get(Math.floorMod(nextInstance++, instances.size()));
    }

    private static void requireNoContent(ResponseEntity<Void> response) {
        if (response.getStatusCode() != HttpStatus.NO_CONTENT) {
            throw new IndexingException("Blog did not confirm the index request");
        }
    }

    private static <T> T required(T response) {
        if (response == null) {
            throw new IndexingException("Blog returned an empty index response");
        }
        return response;
    }
}
