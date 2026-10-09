package com.easyjob.controller;

import com.easyjob.service.AdminStatisticsService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import java.nio.charset.StandardCharsets;

@RestController @RequestMapping("/api/admin/statistics") @RequiredArgsConstructor
public class AdminStatisticsController {
    private final AdminStatisticsService statistics;
    @GetMapping public ResponseVO<?> report(@RequestParam(defaultValue="30") int days,@RequestParam(defaultValue="business") String source) {
        return ResponseVO.success(statistics.statistics(UserContext.getUserId(),days,source));
    }
    @GetMapping("/export") public ResponseEntity<byte[]> export(@RequestParam(defaultValue="30") int days,@RequestParam(defaultValue="business") String source) {
        var report=statistics.statistics(UserContext.getUserId(),days,source);
        byte[] bytes=statistics.workbook(report);
        String filename="EasyJob统计_"+AdminStatisticsService.sourceLabel(source)+"_"+report.from()+"_"+report.to()+".xlsx";
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(filename,StandardCharsets.UTF_8).build().toString())
                .cacheControl(CacheControl.noStore()).contentLength(bytes.length).body(bytes);
    }
}
