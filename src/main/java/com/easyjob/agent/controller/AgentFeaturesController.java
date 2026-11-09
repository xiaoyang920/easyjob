package com.easyjob.agent.controller;

import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import org.springframework.web.bind.annotation.*;
import java.util.HashMap;
import java.util.Map;

/** Agent feedback administration remains inside Java's permission boundary. */
@RestController
@RequestMapping("/api/admin/agent-feedback")
public class AgentFeaturesController {
    private final AgentRpcClient rpc;
    private final AdminConsoleService admin;

    public AgentFeaturesController(AgentRpcClient rpc, AdminConsoleService admin) {
        this.rpc = rpc;
        this.admin = admin;
    }

    @GetMapping
    public ResponseVO<?> report(@RequestParam(defaultValue="1") int page,
        @RequestParam(defaultValue="20") int size, @RequestParam(defaultValue="business") String source) {
        Long uid = UserContext.getUserId();
        admin.requirePermission(uid, "metrics.read");
        return ResponseVO.success(rpc.serviceQuery(uid, "feedback_report", "", "", page, size, source));
    }

    @GetMapping("/{id}")
    public ResponseVO<?> feedbackDetail(@PathVariable String id) {
        Long uid = UserContext.getUserId();
        admin.requirePermission(uid, "feedback.read");
        return ResponseVO.success(rpc.edit(uid, "feedback_detail", id, Map.of()));
    }

    public record FeedbackReview(String state, String note, Long version, String commandId, String generation) {}

    @PutMapping("/{id}/review")
    public ResponseVO<?> reviewFeedback(@PathVariable String id, @RequestBody FeedbackReview request) {
        Long uid = UserContext.getUserId();
        admin.requirePermission(uid, "feedback.manage");
        Map<String, Object> data = new HashMap<>();
        data.put("state", request.state());
        data.put("note", request.note());
        data.put("version", request.version());
        data.put("commandId", request.commandId());
        data.put("generation", request.generation());
        return ResponseVO.success(rpc.edit(uid, "feedback_review", id, data));
    }
}
