package com.easyjob.excel;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.Set;
import java.util.UUID;

@RestController
@RequestMapping("/internal/excel/jobs")
public class ExcelJobController {
    private static final MediaType XLSX = MediaType.parseMediaType(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    private final ExcelJobMapper jobs;
    private final byte[] key;
    private final Path output;

    public ExcelJobController(ExcelJobMapper jobs, @Value("${easyjob.excel.service-key}") String key,
                              @Value("${easyjob.excel.output-dir}") Path output) {
        this.jobs = jobs;
        this.key = key.getBytes(StandardCharsets.UTF_8);
        if (this.key.length < 32) throw new IllegalArgumentException("Excel service key must be at least 32 bytes");
        this.output = output;
    }

    record Submission(long ownerId, UUID requestId, int days, String source, LocalDate from, LocalDate to) {}

    @PostMapping
    public ExcelJob.View submit(@RequestHeader("X-Excel-Key") String supplied, @RequestBody Submission request) {
        authorize(supplied);
        if (request.ownerId() <= 0 || request.requestId() == null || !Set.of(7, 30, 90).contains(request.days())
                || request.source() == null || !Set.of("business", "evaluation", "all").contains(request.source())
                || request.from() == null || request.to() == null
                || ChronoUnit.DAYS.between(request.from(), request.to()) + 1 != request.days()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid export parameters");
        }
        jobs.enqueue(UUID.randomUUID().toString(), request.ownerId(), request.requestId().toString(),
                request.days(), request.source(), request.from(), request.to());
        ExcelJob job = jobs.byRequest(request.ownerId(), request.requestId().toString());
        if (job == null) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
        if (job.days() != request.days() || !job.source().equals(request.source())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Request already used with different parameters");
        }
        return job.view();
    }

    @GetMapping("/{jobNo}")
    public ExcelJob.View status(@RequestHeader("X-Excel-Key") String supplied,
                                @PathVariable UUID jobNo, @RequestParam long ownerId) {
        return ownedJob(supplied, jobNo, ownerId).view();
    }

    @GetMapping("/{jobNo}/file")
    public ResponseEntity<Resource> file(@RequestHeader("X-Excel-Key") String supplied,
                                         @PathVariable UUID jobNo, @RequestParam long ownerId) {
        ExcelJob job = ownedJob(supplied, jobNo, ownerId);
        if (!"succeeded".equals(job.status())) throw new ResponseStatusException(HttpStatus.CONFLICT);
        String name = job.fileName();
        if (name == null || !name.matches(jobNo + "-[a-f0-9-]{36}\\.xlsx")) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
        }
        Path path = output.resolve(name);
        if (!Files.isRegularFile(path)) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).contentType(XLSX)
                .body(new FileSystemResource(path));
    }

    private ExcelJob ownedJob(String supplied, UUID jobNo, long ownerId) {
        authorize(supplied);
        ExcelJob job = jobs.byOwner(jobNo.toString(), ownerId);
        if (job == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        return job;
    }

    private void authorize(String supplied) {
        if (!MessageDigest.isEqual(key, supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        }
    }
}
