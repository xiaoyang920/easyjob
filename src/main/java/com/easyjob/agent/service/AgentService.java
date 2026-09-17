package com.easyjob.agent.service;

import com.alibaba.cloud.ai.graph.CompiledGraph;
import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.RunnableConfig;
import com.alibaba.fastjson2.JSON;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.graph.node.DispatcherNode;
import com.easyjob.agent.graph.node.PlannerNode;
import com.easyjob.agent.graph.node.SynthesizerNode;
import com.easyjob.agent.graph.state.AgentStateFactory;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.AiMessage;
import com.easyjob.vo.ArticleCardVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import com.easyjob.vo.AiChatVO;
import org.springframework.web.client.RestTemplate;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.util.*;

@Slf4j
@Service
public class AgentService {
//    @Autowired
//    @Qualifier("compiledAgentGraph")
//    private CompiledGraph compiledGraph;
//    @Autowired
//    private ChatClient chatClient;
//    @Autowired
//    @Qualifier("deepSeekChatModel")
//    private ChatModel chatModel;
//    @Autowired
//    private AiConversationService aiConversationService;
//    @Autowired
//    private ArticleTool articleTool;
//    @Autowired
//    private BochaSearchTool bochaSearchTool;
//    //图片理解
//    @Autowired
//    private ImageUnderstandingService imageService;
//    @Autowired
//    private RedisComponent redisComponent;
//    @Autowired
//    private EsVectorStore esVectorStore;
//    @Autowired
//    private PlannerNode  plannerNode;
//    @Autowired
//    private DispatcherNode dispatcherNode;
//
//    /**
//     * 非流式聊天 - 通过 Graph 编排并行 Multi-Agent 协作
//     *
//     * 执行流程：
//     * 1. Planner 分析意图，输出执行计划（哪些Worker、是否并行）
//     * 2. Dispatcher 根据计划并行/串行执行Worker
//     * 3. Synthesizer 汇总结果（单Worker透传，多Worker用LLM汇总）
//     */
//    public AiChatVO chat(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
//        // 1. 创建或获取会话
//        final Long finalConvId;
//        if (conversationId == null) {
//            finalConvId = aiConversationService.createConversation(userId);
//        } else {
//            finalConvId = conversationId;
//        }
//
//        // 2. 图片转文字
//        String processedMessage = preprocessMessage(userMessage, imagePaths);
//
//        // 3. 保存用户消息
//        aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);
//
//        // 4. 构建 Graph 输入
//        Map<String, Object> input = new HashMap<>();
//        input.put("userMessage", processedMessage);
//        input.put("conversationId", finalConvId);
//        input.put("userId", userId);
//
//        // 从会话服务拉取历史消息，直接存入 state（无需转换为 Map）
//        List<AiMessage> history = aiConversationService.getContext(finalConvId);
//        input.put("historyMessages", history);
//
//        // 5. 执行 Graph
//        RunnableConfig config = RunnableConfig.builder()
//                .threadId("conv-" + finalConvId)
//                .build();
//
//        Optional<OverAllState> result = compiledGraph.invoke(input, config);
//
//        // 6. 提取结果
//        String reply = result
//                .map(s -> (String) s.value("finalReply").orElse("抱歉，处理出错了"))
//                .orElse("抱歉，处理出错了");
//
//        // 统一从 Redis 取出文章卡片
//        List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
//
//        // 7. 保存AI回复
//        aiConversationService.addMessage(finalConvId, userId, "assistant", reply, null,
//                cards.isEmpty() ? null : cards);
//
//        return AiChatVO.builder()
//                .conversationId(String.valueOf(finalConvId))
//                .reply(reply)
//                .articles(cards)
//                .build();
//    }
//
//    /**
//     * 流式聊天 - Graph Multi-Agent 版
//     *
//     * 执行策略：
//     * 1. 同步执行完整 Graph（Planner → Dispatcher → Synthesizer），拿到 workerResults
//     * 2. 根据 Worker 数量选择流式输出策略：
//     *    - 单Worker：字符分片逐字发出（不额外调LLM）
//     *    - 多Worker：用 ChatClient.stream() 流式汇总多个Worker结果
//     * 3. Graph 执行过程中通过 progressSink 推送阶段性进度事件给前端
//     */
//    public Flux<String> chatStream(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
//        // 1. 创建或获取会话
//        final Long finalConvId;
//        if (conversationId == null) {
//            finalConvId = aiConversationService.createConversation(userId);
//        } else {
//            finalConvId = conversationId;
//        }
//
//        // 2. 图片转文字
//        String processedMessage = preprocessMessage(userMessage, imagePaths);
//
//        // 3. 保存用户消息
//        aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);
//
//        // 4. 构建 Graph 输入
//        Map<String, Object> input = new HashMap<>();
//        input.put("userMessage", processedMessage);
//        input.put("conversationId", finalConvId);
//        input.put("userId", userId);
//
//        // 从会话服务拉取历史消息，直接存入 state（无需转换为 Map）
//        List<AiMessage> history = aiConversationService.getContext(finalConvId);
//        input.put("historyMessages", history);
//
//        // 用于收集完整回复
//        StringBuilder fullReply = new StringBuilder();
//
//        // 所有事件统一通过同一个 sink 发送，避免 Flux.concat 导致 SSE 事件合并
//        return Flux.create(sink -> {
//            Schedulers.boundedElastic().schedule(() -> {
//                try {
//                    // 先发会话ID
//                    sink.next("__CONV_ID__:" + finalConvId);
//
//                    // 构建 OverAllState：先创建空 state，注册策略，再注入输入数据
//                    OverAllState state = new OverAllState();
//                    state.registerKeyAndStrategy(new AgentStateFactory().apply());
//                    state.input(input);
//
//                    // === 阶段1：Planner（分析意图，输出执行计划） ===
//                    sink.next("__PROGRESS__:planner");
//                    Map<String, Object> plannerOutput = plannerNode.apply(state);
//                    state.updateState(plannerOutput);
//
//                    @SuppressWarnings("unchecked")
//                    List<String> activeWorkers = (List<String>) plannerOutput.getOrDefault("activeWorkers", List.of("chat"));
//                    log.info("chatStream Planner完成, activeWorkers: {}", activeWorkers);
//
//                    // === 阶段2：Dispatcher（并行/串行执行Worker） ===
//                    sink.next("__PROGRESS__:dispatcher:" + String.join(",", activeWorkers));
//                    Map<String, Object> dispatcherOutput = dispatcherNode.apply(state);
//                    state.updateState(dispatcherOutput);
//
//                    @SuppressWarnings("unchecked")
//                    List<Map<String, String>> workerResults = (List<Map<String, String>>) dispatcherOutput.getOrDefault("workerResults", List.of());
//                    log.info("chatStream Dispatcher完成, workerResults数: {}", workerResults.size());
//
//                    // === 阶段3：流式输出结果 ===
//                    sink.next("__PROGRESS__:synthesizer");
//
//                    Flux<String> contentFlux;
//                    if (workerResults.size() <= 1) {
//                        // 单 Worker：直接透传结果
//                        String finalReply = workerResults.isEmpty() ? "抱歉，处理出错了"
//                                : workerResults.get(0).get("result");
//                        contentFlux = streamByChunks(finalReply);
//                    } else {
//                        // 多 Worker：LLM 流式汇总
//                        contentFlux = streamSynthesize(processedMessage, workerResults);
//                    }
//
//                    sink.next("__PROGRESS__:done");
//
//                    // 订阅内容流，逐个推送到 sink；完成后发送文章卡片并保存消息
//                    contentFlux.doOnNext(chunk -> {
//                        fullReply.append(chunk);
//                        sink.next(chunk);
//                    }).doOnComplete(() -> {
//                        // 流结束后：取文章卡片、保存消息、发送卡片
//                        List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
//                        aiConversationService.addMessage(finalConvId, userId, "assistant",
//                                fullReply.toString(), null,
//                                (cards != null && !cards.isEmpty()) ? cards : null);
//                        if (cards != null && !cards.isEmpty()) {
//                            sink.next("__ARTICLES__:" + JSON.toJSONString(cards));
//                        }
//                        sink.complete();
//                    }).doOnError(sink::error).subscribe();
//
//                } catch (Exception e) {
//                    log.error("chatStream 执行失败", e);
//                    sink.next("[ERROR] 处理失败，请稍后重试");
//                    sink.complete();
//                }
//            });
//        });
//    }
//
//    /**
//     * 流式聊天 - 单Agent直接对话版
//     *
//     * 使用 ChatClient.stream() 直接与 DeepSeek 对话，支持 Tool 调用（搜索文章、联网搜索）。
//     * 不走 Graph 编排，适合简单问答场景。
//     */
//    public Flux<String> chatStreamSimple(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
//        // 1. 创建或获取会话
//        final Long finalConvId;
//        if (conversationId == null) {
//            finalConvId = aiConversationService.createConversation(userId);
//        } else {
//            finalConvId = conversationId;
//        }
//
//        // 2. 图片转文字
//        String processedMessage = preprocessMessage(userMessage, imagePaths);
//
//        // 3. 保存用户消息
//        aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);
//
//        // 4. 构建历史消息
//        List<AiMessage> history = aiConversationService.getContext(finalConvId);
//        List<org.springframework.ai.chat.messages.Message> messages = new ArrayList<>();
//        for (AiMessage msg : history) {
//            if ("user".equals(msg.getRole())) {
//                messages.add(new org.springframework.ai.chat.messages.UserMessage(msg.getContent()));
//            } else if ("assistant".equals(msg.getRole())) {
//                messages.add(new org.springframework.ai.chat.messages.AssistantMessage(msg.getContent()));
//            }
//        }
//        messages.add(new org.springframework.ai.chat.messages.UserMessage(processedMessage));
//
//        // 5. 用于收集完整回复和文章卡片
//        StringBuilder fullReply = new StringBuilder();
//
//        // 6. 构建带 Tool 的流式请求
//        Flux<String> contentFlux = chatClient.prompt()
//                .messages(messages)
//                .toolContext(Map.of("conversationId", finalConvId))
//                .tools(articleTool, bochaSearchTool)
//                .stream()
//                .content()
//                .doOnNext(fullReply::append);
//
//        return Flux.concat(
//                Flux.just("__CONV_ID__:" + finalConvId),
//                contentFlux,
//                Flux.defer(() -> {
//                    // 从 Redis 提取 Tool 调用过程中产生的文章卡片
//                    List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
//
//                    // 保存AI回复（含卡片）
//                    aiConversationService.addMessage(finalConvId, userId, "assistant",
//                            fullReply.toString(), null,
//                            (cards != null && !cards.isEmpty()) ? cards : null);
//
//                    // 发送文章卡片给前端
//                    if (cards != null && !cards.isEmpty()) {
//                        return Flux.just("__ARTICLES__:" + JSON.toJSONString(cards));
//                    }
//                    return Flux.empty();
//                })
//        );
//    }
//
//    /**
//     * 字符分片流式输出（单Worker透传场景）
//     * 将完整文本按固定大小分片，每片间隔30ms，模拟逐字生成效果。
//     */
//    private Flux<String> streamByChunks(String text) {
//        final int chunkSize = 5;
//        List<String> chunks = new ArrayList<>();
//        for (int i = 0; i < text.length(); i += chunkSize) {
//            chunks.add(text.substring(i, Math.min(i + chunkSize, text.length())));
//        }
//        return Flux.fromIterable(chunks)
//                .delayElements(Duration.ofMillis(30));
//    }
//
//    /**
//     * LLM流式汇总（多Worker场景）
//     * 用 ChatClient.stream() 将多个Worker结果整合为连贯回复，真正逐字输出。
//     */
//    private Flux<String> streamSynthesize(String userMessage, List<Map<String, String>> workerResults) {
//        StringBuilder resultsText = new StringBuilder();
//        for (Map<String, String> wr : workerResults) {
//            resultsText.append(String.format("\n--- %s 的结果 ---\n%s\n",
//                    wr.get("workerName"), wr.get("result")));
//        }
//
//        String synthesizePrompt = """
//                你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。
//
//                【要求】
//                - 不要简单拼接，要有逻辑地组织内容
//                - 保留关键信息，去除重复内容
//                - 使用清晰的结构（标题、列表等）
//                - 语言自然流畅，像是一个人在回答
//                - 不要提及"专家"、"Worker"、"任务"等内部概念
//
//                【用户原始问题】
//                %s
//
//                【各专家的工作结果】
//                %s
//                """.formatted(userMessage, resultsText.toString());
//
//        return ChatClient.builder(chatModel).build()
//                .prompt()
//                .user(synthesizePrompt)
//                .stream()
//                .content();
//    }
//
//    /**
//     * 预处理用户信息
//     */
//    private String preprocessMessage(String userMessage,List<String> imagePaths){
//        if (imagePaths== null|| imagePaths.isEmpty()){
//            return userMessage;
//        }
//        StringBuilder processed = new StringBuilder();
//        log.info("图片数量：{}", imagePaths.size());
//        // 循环处理每张图片（glm-4.6v-flash 不支持多图一次调用）
//        for (int i = 0; i < imagePaths.size(); i++) {
//            String imageDescription = imageService.understandImage(imagePaths.get(i));
//            processed.append(String.format("[图片%d内容：%s]\n", i + 1, imageDescription));
//        }
//        if (userMessage != null && !userMessage.isEmpty()) {
//            processed.append("用户的问题：").append(userMessage);
//        }
//        return processed.toString();
//    }
    private static final String PYTHON_AGENT_URL = "http://localhost:8000";

    private final RestTemplate restTemplate;
    {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);   // 连接超时 5s
        factory.setReadTimeout(120000);    // 读取超时 120s（resume 等 LLM 执行）
        restTemplate = new RestTemplate(factory);
    }
    private final WebClient webClient = WebClient.create(PYTHON_AGENT_URL);

    /**
     * 非流式聊天 → 转发到 Python /chat
     */
    public AiChatVO chat(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
        Map<String, Object> body = Map.of(
                "user_id", userId,
                "conversation_id", conversationId,  // 可为 null，Python 端自动创建
                "message", userMessage,
                "image_paths", imagePaths != null ? imagePaths : List.of()
        );
        String response = restTemplate.postForObject(PYTHON_AGENT_URL + "/chat", body, String.class);
        return JSON.parseObject(response, AiChatVO.class);
    }
    /**
     * 流式聊天 → 转发 Python /chat/stream 的 SSE 流
     */
    public Flux<String> chatStream(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("conversation_id", conversationId);
        body.put("message", userMessage);
        body.put("image_paths", imagePaths);

        return webClient.post().uri("/chat/stream")
                .bodyValue(body)
                .retrieve()
                .bodyToFlux(String.class);
    }

    /**
     * Human-in-the-loop 恢复 → 转发到 Python /chat/resume
     */
    public AiChatVO chatResume(Long conversationId, Long userId, String action) {
        Map<String, Object> body = Map.of(
                "user_id", userId,
                "conversation_id", conversationId,
                "action", action
        );
        String response = restTemplate.postForObject(PYTHON_AGENT_URL + "/chat/resume", body, String.class);
        return JSON.parseObject(response, AiChatVO.class);
    }

    /**
     * Human-in-the-loop 流式恢复 → 转发到 Python /chat/resume/stream
     */
    public Flux<String> chatResumeStream(Long conversationId, Long userId, String action) {
        Map<String, Object> body = Map.of(
                "user_id", userId,
                "conversation_id", conversationId,
                "action", action
        );
        return webClient.post().uri("/chat/resume/stream")
                .bodyValue(body)
                .retrieve()
                .bodyToFlux(String.class);
    }

    /**
     * 暂停执行 → 转发到 Python /chat/{id}/cancel
     */
    public void cancelChat(Long conversationId) {
        restTemplate.postForObject(
                PYTHON_AGENT_URL + "/chat/" + conversationId + "/cancel", null, String.class);
    }
}
