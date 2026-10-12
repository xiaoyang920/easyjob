package com.easyjob.agent.service;

import com.alibaba.fastjson2.JSON;
import com.easyjob.agent.security.AgentServiceAuth;
import com.easyjob.vo.AiChatVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import java.util.*;

@Service
public class AgentService {
    @Value("${agent.python-url:http://localhost:8000}")
    private String pythonUrl = "http://localhost:8000";
    @Autowired private AgentServiceAuth serviceAuth;
    private final RestTemplate restTemplate;
    public AgentService() {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(310000);
        restTemplate = new RestTemplate(factory);
    }
    private Map<String, Object> chatBody(Long cid, Long uid, String message, List<String> images, String requestId, Long originArticleId) {
        if (originArticleId != null && originArticleId <= 0) {
            throw new IllegalArgumentException("来源文章 ID 必须为正数");
        }
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", uid); body.put("conversation_id", cid); body.put("message", message);
        body.put("image_paths", images == null ? List.of() : images);
        body.put("request_id", requestId == null ? UUID.randomUUID().toString() : requestId);
        if (originArticleId != null) body.put("origin_article_id", originArticleId);
        return body;
    }
    private String post(String path, Long uid, Map<String, Object> body) {
        var headers = serviceAuth.headers(uid);
        headers.setContentType(MediaType.APPLICATION_JSON);
        try {
            return restTemplate.postForObject(pythonUrl + path, new HttpEntity<>(body, headers), String.class);
        } catch (HttpStatusCodeException exception) {
            throw upstreamError(exception.getStatusCode(), path);
        }
    }
    private ResponseStatusException upstreamError(HttpStatusCode status, String path) {
        // Expose expected business states without forwarding upstream bodies,
        // which may contain validation payloads or internal diagnostics.
        String message = switch (status.value()) {
            case 409 -> path.contains("/resume")
                    ? "草稿版本已更新或审批已失效，请重新加载会话后确认"
                    : "当前会话已有运行或操作状态已改变，请刷新后重试";
            case 400, 422 -> "请求参数无效，请检查后重试";
            case 401, 403 -> "无权执行当前操作";
            case 404 -> "会话或运行不存在，或已不可访问";
            case 429 -> "请求过于频繁，请稍后重试";
            default -> "智能助手服务暂时不可用，请稍后重试";
        };
        return new ResponseStatusException(status.is5xxServerError() ? HttpStatus.BAD_GATEWAY : status, message);
    }
    private Flux<String> stream(String path, Long uid, Map<String, Object> body) {
        var headers = serviceAuth.headers(uid);
        return WebClient.create(pythonUrl).post().uri(path).headers(h -> h.addAll(headers))
                .bodyValue(body).retrieve()
                .onStatus(HttpStatusCode::isError, response ->
                        response.releaseBody().thenReturn(upstreamError(response.statusCode(), path)))
                .bodyToFlux(String.class);
    }
    public AiChatVO chat(Long cid, Long uid, String message, List<String> images) { return chat(cid, uid, message, images, null); }
    public AiChatVO chat(Long cid, Long uid, String message, List<String> images, String requestId) {
        return chat(cid, uid, message, images, requestId, null);
    }
    public AiChatVO chat(Long cid, Long uid, String message, List<String> images, String requestId, Long originArticleId) {
        return JSON.parseObject(post("/chat", uid, chatBody(cid, uid, message, images, requestId, originArticleId)), AiChatVO.class);
    }
    public Flux<String> chatStream(Long cid, Long uid, String message, List<String> images, String requestId) {
        return chatStream(cid, uid, message, images, requestId, null);
    }
    public Flux<String> chatStream(Long cid, Long uid, String message, List<String> images, String requestId, Long originArticleId) {
        return stream("/chat/stream", uid, chatBody(cid, uid, message, images, requestId, originArticleId));
    }
    private Map<String,Object> resumeBody(Long cid, Long uid, String action, String runId, String hash) {
        return resumeBody(cid,uid,action,runId,hash,null);
    }
    private Map<String,Object> resumeBody(Long cid, Long uid, String action, String runId, String hash,Map<String,String> editedDraft) {
        if (cid == null || action == null || runId == null || hash == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "审批参数缺失，请重新加载会话后操作");
        }
        var body=new HashMap<String,Object>();body.put("user_id",uid);body.put("conversation_id",cid);body.put("action",action);body.put("run_id",runId);body.put("draft_hash",hash);
        if(editedDraft!=null)body.put("edited_draft",editedDraft);
        return body;
    }
    public AiChatVO chatResume(Long cid, Long uid, String action, String runId, String hash) {
        return JSON.parseObject(post("/chat/resume", uid, resumeBody(cid, uid, action, runId, hash)), AiChatVO.class);
    }
    public Flux<String> chatResumeStream(Long cid, Long uid, String action, String runId, String hash) {
        return stream("/chat/resume/stream", uid, resumeBody(cid, uid, action, runId, hash));
    }
    public AiChatVO chatResume(Long cid,Long uid,String action,String runId,String hash,Map<String,String> editedDraft) {
        return JSON.parseObject(post("/chat/resume",uid,resumeBody(cid,uid,action,runId,hash,editedDraft)),AiChatVO.class);
    }
    public Flux<String> chatResumeStream(Long cid,Long uid,String action,String runId,String hash,Map<String,String> editedDraft) {
        return stream("/chat/resume/stream",uid,resumeBody(cid,uid,action,runId,hash,editedDraft));
    }
    public Map<String,Object> cancelChat(Long cid, Long uid) {
        return JSON.parseObject(post("/chat/" + cid + "/cancel?user_id=" + uid, uid, null));
    }
    public Map<String,Object> runStatus(String runId, Long uid) {
        try {
            return JSON.parseObject(restTemplate.exchange(pythonUrl + "/runs/" + runId, HttpMethod.GET,
                    new HttpEntity<>(serviceAuth.headers(uid)), String.class).getBody());
        } catch (HttpStatusCodeException exception) {
            throw upstreamError(exception.getStatusCode(), "/runs/" + runId);
        }
    }
    public Flux<String> recoverRun(String runId, Long uid) {
        try {
            UUID.fromString(runId);
        } catch (IllegalArgumentException invalid) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "运行标识无效");
        }
        return stream("/runs/" + runId + "/recover", uid, Map.of());
    }
    public Map<String,Object> runOverview(Long uid) {
        try {
            return JSON.parseObject(restTemplate.exchange(pythonUrl + "/run-overview", HttpMethod.GET,
                    new HttpEntity<>(serviceAuth.headers(uid)), String.class).getBody());
        } catch (HttpStatusCodeException exception) {
            throw upstreamError(exception.getStatusCode(), "/run-overview");
        }
    }

    public Map<String,Object> conversationRun(Long cid, Long uid) {
        String path = "/conversations/" + cid + "/run";
        try {
            return JSON.parseObject(restTemplate.exchange(pythonUrl + path, HttpMethod.GET,
                    new HttpEntity<>(serviceAuth.headers(uid)), String.class).getBody(), Map.class);
        } catch (HttpStatusCodeException exception) {
            throw upstreamError(exception.getStatusCode(), path);
        }
    }
    public Flux<String> runEvents(String runId, Long uid, long after) {
        UUID.fromString(runId);
        if (after < 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "事件游标无效");
        String path = "/runs/" + runId + "/events?after=" + after;
        return WebClient.create(pythonUrl).get().uri(path).headers(h -> h.addAll(serviceAuth.headers(uid)))
                .retrieve().onStatus(HttpStatusCode::isError, response ->
                        response.releaseBody().thenReturn(upstreamError(response.statusCode(), path)))
                .bodyToFlux(String.class);
    }
    public Map<String,Object> memoryRequest(Long uid, HttpMethod method, String path, Map<String,Object> body) {
        var headers = serviceAuth.headers(uid);
        headers.setContentType(MediaType.APPLICATION_JSON);
        try {
            return JSON.parseObject(restTemplate.exchange(pythonUrl + path, method,
                    new HttpEntity<>(body, headers), String.class).getBody());
        } catch (org.springframework.web.client.HttpStatusCodeException exception) {
            // Preserve conflict/validation status so the editor never reports a stale save as success.
            throw new org.springframework.web.server.ResponseStatusException(exception.getStatusCode(),
                    exception.getStatusCode().value() == 409 ? "记忆已更新，请重新加载后编辑" :
                    exception.getStatusCode().value() == 422 ? "记忆内容或版本格式无效" : "记忆操作未完成");
        }
    }
}
