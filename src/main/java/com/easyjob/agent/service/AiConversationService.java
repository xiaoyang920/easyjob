package com.easyjob.agent.service;

import com.alibaba.fastjson2.JSON;
import com.easyjob.entity.AiConversation;
import com.easyjob.vo.AiHistoryMessageVO;
import com.easyjob.utils.UserContext;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 会话管理服务
 *
 * 【核心功能】
 * 1. 管理对话上下文（Redis）
 * 2. 持久化对话历史（MySQL）
 * 3. 控制上下文长度（最近N轮）
 */
@Service
@Slf4j
public class AiConversationService {
    @Value("${agent.python-url:http://localhost:8000}")
    private String pythonUrl = "http://localhost:8000";
        @Autowired
        private com.easyjob.agent.security.AgentServiceAuth serviceAuth;
        private final RestTemplate restTemplate = new RestTemplate();
        @Autowired(required=false) private com.easyjob.agent.rpc.AgentRpcClient rpc;

        /**
         * 会话列表 → 转发 Python GET /conversations
         */
        public List<AiConversation> getUserConversationsWithCursor(Long userId, LocalDateTime lastUpdateTime,
                                                                   Long lastId, int limit) {
            return getUserConversationsWithCursor(userId, lastUpdateTime, lastId, limit, "all", null);
        }

        public List<AiConversation> getUserConversationsWithCursor(Long userId, LocalDateTime lastUpdateTime,
                                                                   Long lastId, int limit, String scope,
                                                                   Long originArticleId) {
            if (!List.of("all", "general", "article").contains(scope)) {
                throw new IllegalArgumentException("会话范围必须是 all、general 或 article");
            }
            if (originArticleId != null && originArticleId <= 0) {
                throw new IllegalArgumentException("来源文章 ID 必须为正数");
            }
            if (originArticleId != null && "general".equals(scope)) {
                throw new IllegalArgumentException("普通会话不能指定来源文章");
            }
            if (rpc != null) return JSON.parseObject(JSON.toJSONString(rpc.conversations(userId, lastUpdateTime, lastId, limit, scope, originArticleId))).getList("data", AiConversation.class);
            var uri = org.springframework.web.util.UriComponentsBuilder.fromUriString(pythonUrl)
                    .path("/conversations").queryParam("user_id", userId)
                    .queryParam("limit", limit).queryParam("scope", scope);
            if (lastUpdateTime != null) uri.queryParam("last_update_time", lastUpdateTime);
            if (lastId != null) uri.queryParam("last_id", lastId);
            if (originArticleId != null) uri.queryParam("origin_article_id", originArticleId);
            String url = uri.build().encode().toUriString();

            String response = restTemplate.exchange(url, org.springframework.http.HttpMethod.GET,
                    new org.springframework.http.HttpEntity<>(serviceAuth.headers(userId)), String.class).getBody();
            return JSON.parseObject(response).getList("data", AiConversation.class);
        }

        /**
         * 会话元数据，由 Python 校验归属后返回。
         */
        public AiConversation getConversation(Long conversationId) {
            Long userId = UserContext.getUserId();
            if (rpc != null) return JSON.parseObject(JSON.toJSONString(rpc.getConversation(userId, conversationId))).getObject("data", AiConversation.class);
            String response = restTemplate.exchange(
                    pythonUrl + "/conversations/" + conversationId + "?user_id=" + userId,
                    org.springframework.http.HttpMethod.GET,
                    new org.springframework.http.HttpEntity<>(serviceAuth.headers(userId)), String.class).getBody();
            return JSON.parseObject(response).getObject("data", AiConversation.class);
        }

        /**
         * 历史消息 → 转发 Python GET /conversations/{id}/messages
         */
        public List<AiHistoryMessageVO> getContext(Long conversationId) {
            if (rpc != null) return JSON.parseObject(JSON.toJSONString(rpc.history(UserContext.getUserId(), conversationId, false, null, null, null, null, null))).getList("data", AiHistoryMessageVO.class);
            try {
                String response = restTemplate.exchange(
                        pythonUrl + "/conversations/" + conversationId + "/messages?user_id=" + UserContext.getUserId(),
                        org.springframework.http.HttpMethod.GET,
                        new org.springframework.http.HttpEntity<>(serviceAuth.headers(UserContext.getUserId())), String.class).getBody();
                return JSON.parseObject(response).getList("data", AiHistoryMessageVO.class);
            } catch (HttpStatusCodeException error) {
                var status = error.getStatusCode();
                String message = switch (status.value()) {
                    case 404 -> "会话不存在或无权访问";
                    case 401, 403 -> "无权读取当前会话";
                    default -> "暂时无法加载会话记录，请稍后重试";
                };
                throw new ResponseStatusException(status.is5xxServerError() ? HttpStatus.BAD_GATEWAY : status, message);
            }
        }

        /** Bounded history windows and lightweight navigation use the same owner-checked proxy. */
        public Map<String, Object> historyPage(Long conversationId, Integer limit, Long before, Long after, Long around) {
            return historyRequest(conversationId, "messages", Map.of("limit", limit), before, after, around, null);
        }

        public Map<String, Object> questionIndex(Long conversationId, int limit, Long after, Long snapshot) {
            return historyRequest(conversationId, "questions", Map.of("limit", limit), null, after, null, snapshot);
        }

        private Map<String, Object> historyRequest(Long cid, String endpoint, Map<String, Object> parameters,
                                                  Long before, Long after, Long around, Long snapshot) {
            Long uid = UserContext.getUserId();
            if (rpc != null) return JSON.parseObject(JSON.toJSONString(rpc.history(uid, cid, endpoint.equals("questions"), ((Number)parameters.get("limit")).intValue(), before, after, around, snapshot))).getObject("data", Map.class);
            var uri = org.springframework.web.util.UriComponentsBuilder.fromUriString(pythonUrl)
                    .path("/conversations/" + cid + "/" + endpoint).queryParam("user_id", uid);
            parameters.forEach(uri::queryParam);
            if (before != null) uri.queryParam("before", before);
            if (after != null) uri.queryParam("after", after);
            if (around != null) uri.queryParam("around", around);
            if (snapshot != null) uri.queryParam("snapshot", snapshot);
            try {
                String body = restTemplate.exchange(uri.build().encode().toUriString(), org.springframework.http.HttpMethod.GET,
                        new org.springframework.http.HttpEntity<>(serviceAuth.headers(uid)), String.class).getBody();
                return JSON.parseObject(body).getObject("data", Map.class);
            } catch (HttpStatusCodeException error) {
                var status = error.getStatusCode();
                throw new ResponseStatusException(status.is5xxServerError() ? HttpStatus.BAD_GATEWAY : status,
                        status.value() == 404 ? "会话或提问不存在，或无权访问" : "无法加载历史，请检查分页参数或稍后重试");
            }
        }

        /**
         * 删除会话 → 转发 Python DELETE /conversations/{id}
         */
        public void clearContext(Long conversationId) {
            if (rpc != null) { rpc.deleteConversation(UserContext.getUserId(), conversationId); return; }
            restTemplate.exchange(pythonUrl + "/conversations/" + conversationId + "?user_id=" + UserContext.getUserId(),
                    org.springframework.http.HttpMethod.DELETE,
                    new org.springframework.http.HttpEntity<>(serviceAuth.headers(UserContext.getUserId())), String.class);
        }
}
