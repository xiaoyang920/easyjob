package com.easyjob.controller;

import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.AdminStatisticsService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
public class InternalExcelDataController {
    private final AdminStatisticsService statistics;
    private final byte[] key;

    public InternalExcelDataController(AdminStatisticsService statistics,
                                       @Value("${EASYJOB_EXCEL_SERVICE_KEY:}") String key) {
        this.statistics = statistics;
        this.key = key.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping("/internal/excel/community-daily")
    public List<AdminStatisticsService.Daily> daily(
            @RequestHeader(value = "X-Excel-Key", defaultValue = "") String supplied,
            @RequestParam long ownerId,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam String source, @RequestParam int offset, @RequestParam int limit) {
        authorize(supplied);
        try {
            return statistics.exportPage(ownerId, from, to, source, offset, limit);
        } catch (BusinessException error) {
            throw new ResponseStatusException(HttpStatusCode.valueOf(error.getCode()), error.getMessage());
        }
    }

    @PostMapping("/internal/excel/job-finished")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void finished(@RequestHeader(value = "X-Excel-Key", defaultValue = "") String supplied,
                         @RequestBody JobFinished job) {
        authorize(supplied);
        if (job.ownerId() <= 0 || job.jobNo() == null
                || !("succeeded".equals(job.status()) || "failed".equals(job.status()))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        }
        ChatWebSocketHandler.sendToUser(job.ownerId(), Map.of(
                "type", "excel_export_finished", "jobNo", job.jobNo().toString(), "status", job.status()));
    }

    public record JobFinished(UUID jobNo, long ownerId, String status) {}

    @GetMapping("/internal/excel/ready")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void ready(@RequestHeader(value = "X-Excel-Key", defaultValue = "") String supplied) {
        authorize(supplied);
    }

    private void authorize(String supplied) {
        if (key.length < 32 || !MessageDigest.isEqual(key, supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        }
    }
}
