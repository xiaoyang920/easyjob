package com.easyjob.controller;

import com.easyjob.service.AdminStatisticsService;
import com.easyjob.service.AdminStatisticsExcelClient;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import com.easyjob.service.AdminStatisticsService.Report;
import org.springframework.web.server.ResponseStatusException;

@RestController @RequestMapping("/api/admin/statistics") @RequiredArgsConstructor
public class AdminStatisticsController {
    private final AdminStatisticsService statistics;
    private final AdminStatisticsExcelClient excel;

    public record ExportRequest(UUID requestId, int days, String source) {}
    @GetMapping public ResponseVO<?> report(@RequestParam(defaultValue="30") int days,@RequestParam(defaultValue="business") String source) {
        return ResponseVO.success(statistics.statistics(UserContext.getUserId(),days,source));
    }
    @GetMapping("/export") public ResponseEntity<byte[]> export(@RequestParam(defaultValue="30") int days,@RequestParam(defaultValue="business") String source) {
        Report report=statistics.statistics(UserContext.getUserId(),days,source);
        byte[] bytes=statistics.workbook(report);
        String filename="EasyJob统计_"+AdminStatisticsService.sourceLabel(source)+"_"+report.from()+"_"+report.to()+".xlsx";
        return attachment(bytes, filename);
    }

    @PostMapping("/export-jobs")
    public ResponseVO<AdminStatisticsExcelClient.JobView> submitExport(@RequestBody ExportRequest request) {
        Long actor = UserContext.getUserId();
        AdminStatisticsService.DateRange range = statistics.exportRange(actor, request.days(), request.source());
        if (request.requestId() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少导出请求编号");
        }
        return ResponseVO.success(excel.submit(new AdminStatisticsExcelClient.Submission(
                actor, request.requestId(), request.days(), request.source(), range.from(), range.to())));
    }

    @GetMapping("/export-jobs/{jobNo}")
    public ResponseVO<AdminStatisticsExcelClient.JobView> exportStatus(@PathVariable UUID jobNo) {
        Long actor = UserContext.getUserId();
        statistics.requireExportPermission(actor);
        return ResponseVO.success(excel.status(actor, jobNo));
    }

    @GetMapping("/export-jobs/{jobNo}/file")
    public ResponseEntity<byte[]> downloadExport(@PathVariable UUID jobNo) {
        Long actor = UserContext.getUserId();
        statistics.requireExportPermission(actor);
        return attachment(excel.download(actor, jobNo), "EasyJob社区每日统计_" + jobNo + ".xlsx");
    }

    private static ResponseEntity<byte[]> attachment(byte[] bytes, String filename) {
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(filename,StandardCharsets.UTF_8).build().toString())
                .cacheControl(CacheControl.noStore()).contentLength(bytes.length).body(bytes);
    }
}
