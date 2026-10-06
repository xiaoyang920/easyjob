package com.easyjob.controller;
import com.easyjob.service.ReadingGrowthService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController @RequestMapping("/api/reading") @RequiredArgsConstructor
public class ReadingController {
    private final ReadingGrowthService growth;
    public record Start(Long articleId, boolean active) {}
    public record Beat(String sessionId,long sequence,boolean active) {}
    @GetMapping("/me") public ResponseVO<?> me() { return ResponseVO.success(growth.summary(UserContext.getUserId())); }
    @PostMapping("/sessions") public ResponseVO<?> start(@RequestBody Start request) {
        return ResponseVO.success(growth.start(request.articleId(),UserContext.getUserId(),request.active()));
    }
    @PostMapping("/heartbeat") public ResponseVO<?> beat(@RequestBody Beat request) {
        return ResponseVO.success(growth.heartbeat(UserContext.getUserId(),request.sessionId(),request.sequence(),request.active()));
    }
}
