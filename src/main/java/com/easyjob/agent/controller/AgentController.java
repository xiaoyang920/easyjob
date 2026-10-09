package com.easyjob.agent.controller;

import com.easyjob.agent.param.AiChatParam;
import com.easyjob.agent.param.ResumeParam;
import com.easyjob.agent.service.AgentService;
import com.easyjob.agent.service.AiConversationService;
import com.easyjob.entity.AiConversation;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;

import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/agent")
@Slf4j
public class AgentController {
    @GetMapping(value="/runs/{runId}/events", produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<String> runEvents(@PathVariable String runId, @RequestParam(defaultValue="0") long after,
                                 HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-cache");
        response.setHeader("X-Accel-Buffering", "no");
        return agentService.runEvents(runId, UserContext.getUserId(), after);
    }
    @Autowired
    private AgentService agentService;
    @Autowired
    private AiConversationService aiConversationService;

//    /**
//     * 非流式聊天 - Graph Multi-Agent 版（测试用）
//     */
//    @PostMapping("/chat")
//    public ResponseVO chat(@RequestBody AiChatParam param) {
//        Long userId = UserContext.getUserId();
//        if (param.getMessage() == null || param.getMessage().trim().isEmpty()) {
//            return ResponseVO.error("消息不能为空");
//        }
//        return ResponseVO.success(agentService.chat(
//                param.getConversationId(),
//                userId,
//                param.getMessage(),
//                param.getImagePaths()
//        ));
//    }
//
//    /**
//     * 流式聊天 - 根据 mode 切换单Agent/Multi-Agent
//     */
//    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
//    public Flux<String> chatStream(@RequestBody AiChatParam param, HttpServletResponse response) {
//        // 禁用缓冲，确保流式输出
//        response.setHeader("Cache-Control", "no-cache");
//        response.setHeader("X-Accel-Buffering", "no");
//
//        Long userId = UserContext.getUserId();
//        if (param.getMessage() == null || param.getMessage().trim().isEmpty()) {
//            return Flux.just("[ERROR] 消息不能为空");
//        }
//
//        boolean multiAgent = "agent".equals(param.getMode());
//        if (multiAgent) {
//            return agentService.chatStream(
//                    param.getConversationId(),
//                    userId,
//                    param.getMessage(),
//                    param.getImagePaths()
//            );
//        } else {
//            return agentService.chatStreamSimple(
//                    param.getConversationId(),
//                    userId,
//                    param.getMessage(),
//                    param.getImagePaths()
//            );
//        }
//    }
//
//    @GetMapping("/conversations")
//    public ResponseVO getConversations(
//            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime lastUpdateTime,
//            @RequestParam(required = false) Long lastId,
//            @RequestParam(defaultValue = "10") int limit) {
//        Long userId = UserContext.getUserId();
//        List<AiConversation> list = aiConversationService.getUserConversationsWithCursor(userId, lastUpdateTime, lastId, limit);
//        return ResponseVO.success(list);
//    }
//
//    @GetMapping("/conversations/{conversationId}/messages")
//    public ResponseVO getMessages(@PathVariable Long conversationId) {
//        return ResponseVO.success(aiConversationService.getContext(conversationId));
//    }
//
//    @DeleteMapping("/conversations/{conversationId}")
//    public ResponseVO<Void> deleteConversation(@PathVariable Long conversationId) {
//        aiConversationService.clearContext(conversationId);
//        return ResponseVO.success(null);
//    }
        @PostMapping("/chat")
        public ResponseVO chat(@RequestBody AiChatParam param) {
            Long userId = UserContext.getUserId();
            return ResponseVO.success(agentService.chat(
                    param.getConversationId(), userId, param.getMessage(), param.getImagePaths(), param.getRequestId(), param.getOriginArticleId()));
        }

        @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
        public Flux<String> chatStream(@RequestBody AiChatParam param, HttpServletResponse response) {
            response.setHeader("Cache-Control", "no-cache");
            response.setHeader("X-Accel-Buffering", "no");
            Long userId = UserContext.getUserId();
            return agentService.chatStream(
                    param.getConversationId(), userId, param.getMessage(), param.getImagePaths(), param.getRequestId(), param.getOriginArticleId());
        }

        // 新增：Human-in-the-loop 恢复
        @PostMapping("/chat/resume")
        public ResponseVO chatResume(@RequestBody ResumeParam param) {
            Long userId = UserContext.getUserId();
            return ResponseVO.success(agentService.chatResume(
                    param.getConversationId(), userId, param.getAction(), param.getRunId(), param.getDraftHash()));
        }

        // 新增：Human-in-the-loop 流式恢复
        @PostMapping(value = "/chat/resume/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
        public Flux<String> chatResumeStream(@RequestBody ResumeParam param, HttpServletResponse response) {
            response.setHeader("Cache-Control", "no-cache");
            response.setHeader("X-Accel-Buffering", "no");
            Long userId = UserContext.getUserId();
            return agentService.chatResumeStream(
                    param.getConversationId(), userId, param.getAction(), param.getRunId(), param.getDraftHash());
        }

        // 新增：暂停
        @PostMapping("/chat/{conversationId}/cancel")
        public ResponseVO cancelChat(@PathVariable Long conversationId) {
            return ResponseVO.success(agentService.cancelChat(conversationId, UserContext.getUserId()));
        }
        @GetMapping("/conversations")
        public ResponseVO getConversations(
                @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime lastUpdateTime,
                @RequestParam(required = false) Long lastId,
                @RequestParam(defaultValue = "10") int limit,
                @RequestParam(defaultValue = "all") String scope,
                @RequestParam(required = false) Long originArticleId) {
            Long userId = UserContext.getUserId();
            List<AiConversation> list = aiConversationService.getUserConversationsWithCursor(
                    userId, lastUpdateTime, lastId, limit, scope, originArticleId);
            return ResponseVO.success(list);
        }

        @GetMapping("/conversations/{conversationId}/messages")
        public ResponseVO getMessages(@PathVariable Long conversationId) {
            return ResponseVO.success(aiConversationService.getContext(conversationId));
        }

        @DeleteMapping("/conversations/{conversationId}")
        public ResponseVO<Void> deleteConversation(@PathVariable Long conversationId) {
            aiConversationService.clearContext(conversationId);
            return ResponseVO.success(null);
        }

        @GetMapping("/conversations/{conversationId}")
        public ResponseVO getConversation(@PathVariable Long conversationId) {
            return ResponseVO.success(aiConversationService.getConversation(conversationId));
        }
        @GetMapping("/run-overview")
        public ResponseVO runOverview() {
            return ResponseVO.success(agentService.runOverview(UserContext.getUserId()));
        }

        @GetMapping("/runs/{runId}")
        public ResponseVO runStatus(@PathVariable String runId) {
            return ResponseVO.success(agentService.runStatus(runId, UserContext.getUserId()));
        }

        @PostMapping(value = "/runs/{runId}/recover", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
        public Flux<String> recoverRun(@PathVariable String runId) {
            return agentService.recoverRun(runId, UserContext.getUserId());
        }

        @GetMapping("/conversations/{conversationId}/run")
        public ResponseVO conversationRun(@PathVariable Long conversationId) {
            return ResponseVO.success(agentService.conversationRun(conversationId, UserContext.getUserId()));
        }
}
