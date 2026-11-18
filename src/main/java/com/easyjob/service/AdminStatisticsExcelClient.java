package com.easyjob.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.util.UUID;
import java.util.function.Supplier;

@Service
public class AdminStatisticsExcelClient {
    private final RestClient client;
    private final boolean configured;

    public AdminStatisticsExcelClient(@Value("${EASYJOB_EXCEL_URL:http://127.0.0.1:8083}") String url,
                                      @Value("${EASYJOB_EXCEL_SERVICE_KEY:}") String key) {
        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(http);
        factory.setReadTimeout(Duration.ofSeconds(10));
        this.configured = key.getBytes(StandardCharsets.UTF_8).length >= 32;
        this.client = RestClient.builder().baseUrl(url).requestFactory(factory)
                .defaultHeader("X-Excel-Key", key).build();
    }

    public record Submission(Long ownerId, UUID requestId, int days, String source, LocalDate from, LocalDate to) {}
    public record JobView(String jobNo, String status, int attempts, Integer rowCount, String error,
                          LocalDate from, LocalDate to, String source) {}

    public JobView submit(Submission request) {
        return call(() -> client.post().uri("/internal/excel/jobs").body(request).retrieve().body(JobView.class),
                "同一个请求编号已用于其他统计条件");
    }

    public JobView status(Long owner, UUID jobNo) {
        return call(() -> client.get().uri("/internal/excel/jobs/{jobNo}?ownerId={owner}", jobNo, owner)
                .retrieve().body(JobView.class), "");
    }

    public byte[] download(Long owner, UUID jobNo) {
        return call(() -> client.get().uri("/internal/excel/jobs/{jobNo}/file?ownerId={owner}", jobNo, owner)
                .retrieve().body(byte[].class), "导出文件尚未生成");
    }

    private <T> T call(Supplier<T> request, String conflictMessage) {
        if (!configured) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Excel 导出服务尚未配置");
        try {
            T result = request.get();
            if (result == null) throw unavailable(null);
            return result;
        } catch (RestClientResponseException error) {
            if (error.getStatusCode() == HttpStatus.NOT_FOUND) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "导出任务不存在");
            }
            if (error.getStatusCode() == HttpStatus.CONFLICT) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, conflictMessage);
            }
            throw unavailable(error);
        } catch (RestClientException error) {
            throw unavailable(error);
        }
    }

    private static ResponseStatusException unavailable(Throwable cause) {
        return new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Excel 导出服务暂时不可用", cause);
    }
}
