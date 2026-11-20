package com.easyjob.excel;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.io.IOException;
import java.net.http.HttpClient;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.List;
import java.util.UUID;

@Component
public class ExcelWorker {
    private static final Logger log = LoggerFactory.getLogger(ExcelWorker.class);
    private static final int MAX_ATTEMPTS = 3;
    private static final int LEASE_SECONDS = 60;
    private static final ParameterizedTypeReference<List<DailyWorkbook.Daily>> DAILY_ROWS =
            new ParameterizedTypeReference<>() {};
    private final ExcelJobMapper jobs;
    private final RestClient blog;
    private final RestClient notifications;
    private final Path output;
    private final int pageSize;

    public ExcelWorker(ExcelJobMapper jobs, @Value("${easyjob.excel.blog-url}") String blogUrl,
                       @Value("${easyjob.excel.service-key}") String key,
                       @Value("${easyjob.excel.output-dir}") Path output,
                       @Value("${easyjob.excel.page-size}") int pageSize) throws IOException {
        if (pageSize < 1 || pageSize > 50) throw new IllegalArgumentException("Excel page size must be 1 to 50");
        this.jobs = jobs;
        this.output = Files.createDirectories(output);
        this.pageSize = pageSize;
        JdkClientHttpRequestFactory http = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build());
        http.setReadTimeout(Duration.ofSeconds(12));
        this.blog = RestClient.builder().baseUrl(blogUrl).requestFactory(http).defaultHeader("X-Excel-Key", key).build();
        JdkClientHttpRequestFactory notificationHttp = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build());
        notificationHttp.setReadTimeout(Duration.ofSeconds(2));
        this.notifications = blog.mutate().requestFactory(notificationHttp).build();
    }

    @Scheduled(fixedDelayString = "${easyjob.excel.scan-delay-ms}")
    void scan() {
        for (ExcelJob job : jobs.exhaustedCandidates(MAX_ATTEMPTS)) {
            if (jobs.exhaust(job.jobNo(), MAX_ATTEMPTS) == 1) notifyFinished(job, "failed");
        }
        for (String jobNo : jobs.candidates(MAX_ATTEMPTS)) {
            String token = UUID.randomUUID().toString();
            if (jobs.claim(jobNo, token, MAX_ATTEMPTS, LEASE_SECONDS) == 1) {
                ExcelJob job = jobs.byLease(jobNo, token);
                if (job != null) execute(job, token);
                return;
            }
        }
    }

    private void execute(ExcelJob job, String token) {
        String fileName = job.jobNo() + "-" + token + ".xlsx";
        Path partial = output.resolve(fileName + ".part");
        Path published = output.resolve(fileName);
        try {
            int rows = DailyWorkbook.write(partial, job.fromDay(), job.days(), pageSize, offset -> {
                renew(job, token);
                return blog.get().uri(builder -> builder.path("/internal/excel/community-daily")
                                .queryParam("ownerId", job.ownerId()).queryParam("from", job.fromDay())
                                .queryParam("to", job.toDay()).queryParam("source", job.source())
                                .queryParam("offset", offset).queryParam("limit", pageSize).build())
                        .retrieve().body(DAILY_ROWS);
            });
            renew(job, token);
            Files.move(partial, published, StandardCopyOption.ATOMIC_MOVE);
            // If the database response is lost after commit, retain this file.
            if (jobs.succeed(job.jobNo(), token, fileName, rows) == 1) {
                notifyFinished(job, "succeeded");
            } else {
                delete(published);
            }
        } catch (LeaseLostException ignored) {
            log.info("Excel job {} lost its lease", job.jobNo());
        } catch (Exception error) {
            boolean denied = error instanceof RestClientResponseException response
                    && response.getStatusCode() == HttpStatus.FORBIDDEN;
            boolean terminal = denied || job.attempts() >= MAX_ATTEMPTS;
            int updated = jobs.fail(job.jobNo(), token, terminal ? "failed" : "pending",
                    denied ? "permission_denied" : "export_failed", 5 * job.attempts());
            if (updated == 1 && terminal) notifyFinished(job, "failed");
            log.warn("Excel job {} attempt {} failed ({})", job.jobNo(), job.attempts(), error.getClass().getSimpleName());
        } finally {
            delete(partial);
        }
    }

    private void notifyFinished(ExcelJob job, String status) {
        try {
            notifications.post().uri("/internal/excel/job-finished")
                    .body(new JobFinished(job.jobNo(), job.ownerId(), status)).retrieve().toBodilessEntity();
        } catch (RuntimeException error) {
            log.warn("Could not push Excel job {} result ({})", job.jobNo(), error.getClass().getSimpleName());
        }
    }

    private record JobFinished(String jobNo, long ownerId, String status) {}

    private void renew(ExcelJob job, String token) {
        if (jobs.renew(job.jobNo(), token, LEASE_SECONDS) != 1) throw new LeaseLostException();
    }

    private void delete(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException error) {
            log.warn("Could not remove Excel attempt file {}", path.getFileName());
        }
    }

    private static final class LeaseLostException extends RuntimeException {}
}
