package com.easyjob.controller;
import com.easyjob.service.AdminAgentMetricsService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api/admin/agent-metrics") @RequiredArgsConstructor
public class AdminAgentMetricsController {
 private final AdminAgentMetricsService service;
 @GetMapping public ResponseVO<?> report(@RequestParam(defaultValue="7") int days,@RequestParam(defaultValue="business") String source){return ResponseVO.success(service.report(UserContext.getUserId(),days,source));}
}
