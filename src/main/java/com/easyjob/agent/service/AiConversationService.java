package com.easyjob.agent.service;

import com.alibaba.fastjson2.JSON;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.AiConversation;
import com.easyjob.entity.AiMessage;
import com.easyjob.vo.AiHistoryMessageVO;
import com.easyjob.mapper.AiConversationMapper;
import com.easyjob.mapper.AiMessageMapper;
import com.easyjob.vo.ArticleCardVO;
import com.easyjob.utils.UserContext;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
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
//    @Autowired
//    private RedisComponent redisComponent;
//    @Autowired
//    private AiConversationMapper aiConversationMapper;
//    @Autowired
//    private AiMessageMapper aiMessageMapper;
//
//    @Value("${agent.conversation.max-rounds:20}")
//    private int maxRounds;
//    /**
//     * 获取会话上下文
//     *
//     * 【流程】
//     * 1. 先从Redis获取
//     * 2. Redis没有则从MySQL加载
//     * 3. 只返回最近maxRounds轮对话
//     *
//     * @param conversationId 会话ID
//     * @return 消息列表 [{role, content}, ...]
//     */
//    public List<AiMessage> getContext(Long conversationId){
//        // 从Redis获取
//        List<AiMessage> cached = redisComponent.getConversationContext(conversationId);
//        if (cached != null) {
//            log.debug("从Redis获取会话上下文: {}", conversationId);
//            return cached;
//        }
//        // redis没有从MySQL加载
//        List<AiMessage> messages = aiMessageMapper.selectByConversationId(conversationId);
//        if(messages.isEmpty()){
//            return new ArrayList<>();
//        }
//        // 截取
//        messages = truncateContext(messages);
//        //缓存到redis
//        redisComponent.saveConversationContext(conversationId, messages);
//        log.debug("从MySQL加载会话上下文并缓存: {}", conversationId);
//        return messages;
//    }
//    /**
//     * 添加消息到会话
//     *
//     * @param conversationId 会话ID
//     * @param userId 用户ID
//     * @param role 角色 (user/assistant)
//     * @param content 内容
//     * @param imagePaths 图片路径列表（可为null或空）
//     */
//    public void addMessage(Long conversationId, Long userId, String role, String content, List<String> imagePaths,List<ArticleCardVO> articleCards){
//        //获取会话
//        List<AiMessage> context = getContext(conversationId);
//        //添加消息
//        AiMessage message = new AiMessage();
//        message.setConversationId(conversationId);
//        message.setRole(role);
//        message.setContent(content);
//        message.setImagePaths(imagePaths);
//        message.setCreateTime(LocalDateTime.now());
//        message.setArticleCards(articleCards); // 可为null
//        context.add(message);
//        //截取消息
//        context = truncateContext(context);
//        //更新redis
//        redisComponent.saveConversationContext(conversationId, context);
//        //更新MySQL
//        saveToMysql(conversationId, userId, role, content, imagePaths, articleCards);
//        log.debug("添加消息到会话: {}, role={}", conversationId, role);
//    }
//    /**
//     * 创建新会话
//     * @param userId 用户ID
//     * @return 会话ID
//     */
//    public Long createConversation(Long userId){
//        AiConversation conversation = new AiConversation();
//        conversation.setUserId(userId);
//        conversation.setMessageCount(0);
//        conversation.setCreateTime(LocalDateTime.now());
//        conversation.setUpdateTime(LocalDateTime.now());
//        conversation.setStatus(1);
//        aiConversationMapper.insert(conversation);  // 插入后MyBatis-Plus会自动回填雪花ID
//        Long conversationId = conversation.getConversationId();
//        log.info("创建新会话: {}, userId={}", conversationId, userId);
//        return conversationId;
//     }
//     /**
//     * 获取用户会话列表
//     * @param userId
//     * @param limit
//     * @return
//     */
//     public List<AiConversation> getUserConversations(Long userId,int limit){
//        return aiConversationMapper.selectByUserId(userId,limit);
//    }
//    /**
//     * 清除会话上下文（开始新对话）
//     */
//    @Transactional
//    public void clearContext(Long conversationId) {
//        aiMessageMapper.delete(new LambdaQueryWrapper<>(AiMessage.class).eq(AiMessage::getConversationId, conversationId));
//        aiConversationMapper.deleteById(conversationId);
//        redisComponent.deleteConversationContext(conversationId);
//        log.info("清除会话上下文: {}", conversationId);
//    }
//    /**
//     * 保存消息到MySQL
//     * @param conversationId
//     * @param userId
//     * @param role
//     * @param content
//     * @param imagePaths
//     */
//    private void saveToMysql(Long conversationId, Long userId, String role, String content, List<String> imagePaths,List<ArticleCardVO> articleCards){
//        AiMessage message = new AiMessage();
//        message.setConversationId(conversationId);
//        message.setRole(role);
//        message.setContent(content);
//        message.setImagePaths(imagePaths);
//        message.setCreateTime(LocalDateTime.now());
//        message.setArticleCards(articleCards);  // 可为null
//        aiMessageMapper.insert(message);
//
//        // 更新会话消息数
//        aiConversationMapper.incrementMessageCount(conversationId);
//
//        //如果是第一条用户消息，则更新会话标题
//        // 如果是第一条用户消息，设置为会话标题
//        if ("user".equals(role)) {
//            AiConversation conv = aiConversationMapper.selectById(conversationId);
//            if (conv != null && conv.getTitle() == null) {
//                String title = content.length() > 50 ? content.substring(0, 50) + "..." : content;
//                aiConversationMapper.updateTitle(conversationId, title);
//            }
//        }
//    }
//    /**
//     * 截取会话上下文
//     * @param context
//     * @return
//     */
//    private List<AiMessage> truncateContext(List<AiMessage> context){
//        int keepCount = maxRounds * 2;
//        // 如果小于最大轮数，则返回
//        if(context.size() <= keepCount){
//            return context;
//        }
//        //如果有系统信息,始终保存
//        AiMessage systemMsg = null;
//        List<AiMessage> nonSystemMsgs = new ArrayList<>();
//        // 如果大于最大轮数，则截取
//        for(AiMessage msg : context){
//            if(msg.getRole().equals("system")){
//                systemMsg = msg;
//            }else {
//                nonSystemMsgs.add(msg);
//            }
//        }
//        if(nonSystemMsgs.size()>=keepCount){
//            nonSystemMsgs = nonSystemMsgs.subList(nonSystemMsgs.size()-keepCount, nonSystemMsgs.size());
//        }
//        List<AiMessage> result = new ArrayList<>();
//        if(systemMsg != null){
//            result.add(systemMsg);
//        }
//        result.addAll(nonSystemMsgs);
//        return result;
//    }
//
//    public List<AiConversation> getUserConversationsWithCursor(Long userId, LocalDateTime lastUpdateTime, Long lastId, int limit) {
//        return aiConversationMapper.selectByUserIdWithCursor(userId, lastUpdateTime, lastId, limit);
//    }
    @Value("${agent.python-url:http://localhost:8000}")
    private String pythonUrl = "http://localhost:8000";
        @Autowired
        private com.easyjob.agent.security.AgentServiceAuth serviceAuth;
        private final RestTemplate restTemplate = new RestTemplate();

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
            restTemplate.exchange(pythonUrl + "/conversations/" + conversationId + "?user_id=" + UserContext.getUserId(),
                    org.springframework.http.HttpMethod.DELETE,
                    new org.springframework.http.HttpEntity<>(serviceAuth.headers(UserContext.getUserId())), String.class);
        }
}
