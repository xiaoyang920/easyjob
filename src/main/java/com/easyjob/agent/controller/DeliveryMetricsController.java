package com.easyjob.agent.controller;

import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.exception.BusinessException;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
import java.util.UUID;

@RestController @RequestMapping("/api/agent/runs") @RequiredArgsConstructor
public class DeliveryMetricsController {
    private final AgentRpcClient rpc;
    public record Sample(Long firstAnswerMs) {}
    @PostMapping("/{runId}/delivery-metrics")
    public ResponseVO<?> record(@PathVariable String runId,@RequestBody Sample sample) {
        Long uid=UserContext.getUserId();
        if(uid==null)throw new BusinessException(401,"请先登录");
        try{UUID.fromString(runId);}catch(IllegalArgumentException e){throw new BusinessException("运行标识无效");}
        if(sample.firstAnswerMs()==null || sample.firstAnswerMs()<0 || sample.firstAnswerMs()>3600000)throw new BusinessException("耗时范围无效");
        return ResponseVO.success(rpc.edit(uid,"delivery_metrics",runId,Map.of("first_answer_ms",sample.firstAnswerMs())));
    }
}
