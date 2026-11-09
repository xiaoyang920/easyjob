> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# 流式输出方案B：全链路流式（Worker 级流式）

> 本文档是 `12-multi-agent-alibaba-graph.md` 中方案A（Synthesizer 流式）的进阶替代方案。
> 方案A 的策略是 Planner + Dispatcher 同步执行，只在最终输出阶段流式。
> 方案B 的策略是**单 Worker 场景下，Worker 本身就流式输出**，减少用户等待时间。
>
> 建议先实现方案A跑通，再考虑是否需要升级到方案B。

## 一、方案对比

| 维度 | 方案A：Synthesizer 流式 | 方案B：全链路流式（本文档） |
|------|------------------------|--------------------------|
| 单Worker流式起点 | Dispatcher 执行完后才开始流式 | Worker 内部直接流式输出，跳过 Synthesizer |
| 多Worker流式起点 | 所有 Worker 完成后，Synthesizer 流式汇总 | 同方案A（无法更早） |
| 单Worker用户等待 | Planner ~1s + Worker ~2s + 字符分片 ~0s = ~3s 后开始 | Planner ~1s 后直接开始逐字输出 = ~1s 后开始 |
| 多Worker用户等待 | 同方案A | 同方案A |
| 改动量 | AgentService 新增 chatStream + 辅助方法 | AgentService 大改 + Worker 新增流式方法 + StreamContext 类 |
| 架构复杂度 | 低（手动编排3步） | 中高（需要动态选择流式策略、Worker 双模式） |
| AgentService 依赖 | 需要注入 ChatModel、Tool 等 | 同方案A |
| 前端改动 | 无 | 无 |

**核心收益**：单 Worker 场景（闲聊、单独搜索等最常见场景）的首字延迟从 ~3秒降到 ~1秒。

**核心成本**：Worker 需要支持同步和流式两种模式，代码复杂度增加。

## 二、架构设计

### 2.1 流式策略选择

```
用户发送消息
    │
    ▼
PlannerNode.apply(state)  ← 同步执行（~1秒）
    │
    ├── activeWorkers.size() == 1 且不是依赖链
    │   │
    │   ▼
    │   Worker 流式执行（.stream().content() → Flux<String>）
    │   │
    │   └── 直接透传给前端（跳过 Synthesizer）
    │
    └── activeWorkers.size() > 1 或包含依赖链
        │
        ▼
        DispatcherNode.apply(state)  ← 同步执行（Worker 并行）
        │
        ▼
        Synthesizer 流式汇总（同方案A）
```

### 2.2 关键区别

方案A 中，单 Worker 场景的执行路径是：
```
Planner(同步) → Dispatcher(同步，内部执行Worker) → 字符分片输出
```
Worker 已经同步执行完了，拿到的是完整文本，只能做字符分片模拟流式。

方案B 中，单 Worker 场景的执行路径是：
```
Planner(同步) → Worker 流式执行（.stream().content()）→ 真正逐字输出
```
Worker 用 `.stream()` 调用 LLM，每生成一个 token 就实时发给前端，是真正的流式。

## 三、核心代码

### 3.1 Worker 流式接口

每个 Worker 需要新增一个 `applyStream()` 方法，返回 `Flux<String>` 而不是 `Map<String, Object>`。

原有的 `apply()` 方法（同步版）保持不变，供 Graph 非流式执行和 Dispatcher 并行调度使用。


#### 3.1.1 StreamableWorker 接口

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import reactor.core.publisher.Flux;

/**
 * 可流式输出的 Worker 接口
 * 
 * Worker 同时实现 NodeAction（同步）和 StreamableWorker（流式）两个接口：
 * - apply()：同步执行，返回完整结果。用于 Graph 非流式执行和 Dispatcher 并行调度
 * - applyStream()：流式执行，返回 Flux<String>。用于单 Worker 场景的真正流式输出
 * 
 * 为什么不直接改 apply() 为流式？
 * 因为 Graph 框架的 NodeAction 接口要求 apply() 返回 Map<String, Object>，
 * 这是同步的契约，不能改。流式是额外能力，通过新接口提供。
 */
public interface StreamableWorker {

    /**
     * 流式执行 Worker
     * 
     * @param state 全局状态（包含 taskDescriptions 等）
     * @return 流式文本输出
     */
    Flux<String> applyStream(OverAllState state);
}
```

#### 3.1.2 ChatWorkerNode 实现流式

以 ChatWorkerNode 为例，展示如何同时支持同步和流式：

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 聊天Worker节点（同步 + 流式双模式）
 */
@Slf4j
public class ChatWorkerNode implements NodeAction, StreamableWorker {

    private final ChatModel chatModel;

    private static final String CHAT_SYSTEM_PROMPT = """
            你是一个智能博客平台助手，负责日常对话和技术问答。
            
            【职责】
            - 友好地回答用户的各种问题
            - 解答技术概念和编程知识
            - 提供学习建议和技术指导
            
            【当前日期】%s
            
            【输出要求】
            - 回答简洁、准确、有帮助
            - 使用列表格式提高可读性
            - 如果不确定，诚实告知
            """;

    public ChatWorkerNode(ChatModel chatModel) {
        this.chatModel = chatModel;
    }

    /**
     * 同步执行（Graph 非流式 / Dispatcher 并行调度使用）
     * 与原版完全一致，不做任何改动
     */
    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        String today = java.time.LocalDate.now().toString();
        boolean degraded = state.value("degraded", false);
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("chat", state.value("userMessage", ""));

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(CHAT_SYSTEM_PROMPT.formatted(today))
                .build();

        String result;
        if (degraded) {
            List<Map<String, String>> history = state.value("historyMessages", List.of());
            List<Message> messages = new ArrayList<>();
            for (Map<String, String> msg : history) {
                if ("user".equals(msg.get("role"))) {
                    messages.add(new UserMessage(msg.get("content")));
                } else if ("assistant".equals(msg.get("role"))) {
                    messages.add(new AssistantMessage(msg.get("content")));
                }
            }
            messages.add(new UserMessage(taskInput));
            result = workerClient.prompt().messages(messages).call().content();
        } else {
            result = workerClient.prompt().user(taskInput).call().content();
        }

        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "chat");
        workerResult.put("result", result);
        return Map.of("workerResults", workerResult);
    }

    /**
     * 流式执行（单 Worker 场景，直接逐字输出给前端）
     * 
     * 与 apply() 的区别：
     * - apply() 用 .call().content() 同步获取完整结果
     * - applyStream() 用 .stream().content() 获取 Flux<String>，逐字输出
     */
    @Override
    @SuppressWarnings("unchecked")
    public Flux<String> applyStream(OverAllState state) {
        String today = java.time.LocalDate.now().toString();
        boolean degraded = state.value("degraded", false);
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("chat", state.value("userMessage", ""));

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(CHAT_SYSTEM_PROMPT.formatted(today))
                .build();

        if (degraded) {
            List<Map<String, String>> history = state.value("historyMessages", List.of());
            List<Message> messages = new ArrayList<>();
            for (Map<String, String> msg : history) {
                if ("user".equals(msg.get("role"))) {
                    messages.add(new UserMessage(msg.get("content")));
                } else if ("assistant".equals(msg.get("role"))) {
                    messages.add(new AssistantMessage(msg.get("content")));
                }
            }
            messages.add(new UserMessage(taskInput));
            return workerClient.prompt().messages(messages).stream().content();
        } else {
            return workerClient.prompt().user(taskInput).stream().content();
        }
    }
}
```

#### 3.1.3 SearchWorkerNode 流式的特殊性

SearchWorkerNode 有 Tool Calling，流式场景下 Tool Calling 的行为需要注意：

```java
/**
 * SearchWorkerNode 的流式版本
 * 
 * 【重要】Tool Calling + 流式的行为：
 * Spring AI 的 .stream().content() 在遇到 Tool Calling 时，会先同步执行 Tool，
 * 拿到 Tool 结果后，再流式输出 LLM 的最终回复。
 * 
 * 所以 SearchWorkerNode 的流式体验是：
 * 1. 等待 Tool 执行（搜索文章，~1-2秒，这段时间前端无输出）
 * 2. Tool 执行完后，LLM 开始流式生成回复（前端逐字显示）
 * 
 * 这比方案A好在：方案A 要等 Worker 完全执行完才开始字符分片，
 * 方案B 在 Tool 执行完后就开始真正流式了。
 */
@Override
@SuppressWarnings("unchecked")
public Flux<String> applyStream(OverAllState state) {
    Long conversationId = state.value("conversationId", 0L);
    String today = java.time.LocalDate.now().toString();
    Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
    String taskInput = taskDescriptions.getOrDefault("search", state.value("userMessage", ""));

    String ragContext = retrieveRagContext(taskInput);
    String systemPrompt = SEARCH_SYSTEM_PROMPT.formatted(today);
    if (!ragContext.isEmpty()) {
        systemPrompt += "\n\n【RAG参考资料】\n" + ragContext;
    }

    ChatClient workerClient = ChatClient.builder(chatModel)
            .defaultSystem(systemPrompt)
            .build();

    return workerClient.prompt()
            .user(taskInput)
            .tools(articleTool, bochaSearchTool)
            .toolContext(Map.of("conversationId", conversationId))
            .stream()
            .content();
}
```

> **注意**：SearchWorkerNode 流式版本有一个问题——文章卡片（`articleCards`）的获取时机。
> 同步版本中，Worker 执行完后从 Redis 获取卡片。流式版本中，流还没结束就无法确定 Tool 是否已执行完。
> 解决方案：在 AgentService 层，流结束后（`doOnComplete`）再从 Redis 获取卡片。

### 3.2 AgentService.chatStream 方案B版本

```java
/**
 * 流式聊天 - 方案B：全链路流式
 * 
 * 与方案A的核心区别：
 * - 单Worker场景：Worker 内部直接 .stream() 流式输出，不经过 Dispatcher
 * - 多Worker场景：同方案A（Dispatcher 同步 + Synthesizer 流式汇总）
 * 
 * 单Worker场景的首字延迟：Planner ~1秒后直接开始逐字输出
 * 多Worker场景的首字延迟：同方案A（~3秒）
 */
public Flux<String> chatStream(Long conversationId, Long userId,
                                String userMessage, List<String> imagePaths) {
    final Long finalConvId = conversationId != null ? conversationId
            : aiConversationService.createConversation(userId);

    String processedMessage = preprocessMessage(userMessage, imagePaths);
    aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);

    List<AiMessage> history = aiConversationService.getContext(finalConvId);
    List<Map<String, String>> historyMaps = new ArrayList<>();
    for (AiMessage msg : history) {
        historyMaps.add(Map.of("role", msg.getRole(), "content", msg.getContent()));
    }

    StringBuilder fullReply = new StringBuilder();
    AtomicReference<List<ArticleCardVO>> articleCardsRef = new AtomicReference<>(List.of());

    return Flux.concat(
            Flux.just("__CONV_ID__:" + finalConvId),

            Flux.defer(() -> {
                try {
                    // === 同步阶段：执行 Planner ===
                    OverAllState state = buildState(Map.of(
                            "userMessage", processedMessage,
                            "conversationId", finalConvId,
                            "userId", userId,
                            "historyMessages", historyMaps
                    ));

                    PlannerNode planner = new PlannerNode(chatModel);
                    Map<String, Object> plannerOutput = planner.apply(state);
                    state = mergeState(state, plannerOutput);

                    @SuppressWarnings("unchecked")
                    List<String> activeWorkers = (List<String>) plannerOutput.getOrDefault(
                            "activeWorkers", List.of("chat"));
                    boolean isSingleWorker = activeWorkers.size() == 1
                            && !activeWorkers.get(0).contains("_then_");

                    log.info("chatStream Planner完成, activeWorkers: {}, 单Worker模式: {}",
                            activeWorkers, isSingleWorker);

                    if (isSingleWorker) {
                        // === 单Worker：直接流式输出 ===
                        return streamSingleWorker(activeWorkers.get(0), state,
                                finalConvId, fullReply, articleCardsRef);
                    } else {
                        // === 多Worker：Dispatcher同步 + Synthesizer流式汇总 ===
                        return streamMultiWorker(state, processedMessage,
                                finalConvId, fullReply, articleCardsRef);
                    }
                } catch (Exception e) {
                    log.error("chatStream Planner执行失败", e);
                    return Flux.just("[ERROR] 处理失败，请稍后重试");
                }
            }),

            // 流结束后保存回复 + 发送文章卡片
            Flux.defer(() -> {
                List<ArticleCardVO> cards = articleCardsRef.get();
                aiConversationService.addMessage(finalConvId, userId, "assistant",
                        fullReply.toString(), null, cards.isEmpty() ? null : cards);

                if (!cards.isEmpty()) {
                    return Flux.just("__ARTICLES__:" + JSON.toJSONString(cards));
                }
                return Flux.empty();
            })
    );
}

/**
 * 单Worker流式输出
 * 
 * Worker 实现了 StreamableWorker 接口，直接调用 applyStream() 获取 Flux<String>。
 * 每个 token 实时发给前端，是真正的逐字流式。
 */
private Flux<String> streamSingleWorker(String workerName, OverAllState state,
                                         Long conversationId, StringBuilder fullReply,
                                         AtomicReference<List<ArticleCardVO>> articleCardsRef) {
    StreamableWorker worker = createStreamableWorker(workerName);

    return worker.applyStream(state)
            .doOnNext(fullReply::append)
            .doOnComplete(() -> {
                // 流结束后获取文章卡片（SearchWorker 的 Tool 可能产生了卡片）
                List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(conversationId);
                articleCardsRef.set(cards);
                log.info("单Worker[{}]流式完成, 回复长度: {}, 卡片数: {}",
                        workerName, fullReply.length(), cards.size());
            });
}

/**
 * 多Worker流式汇总（同方案A逻辑）
 */
private Flux<String> streamMultiWorker(OverAllState state, String userMessage,
                                        Long conversationId, StringBuilder fullReply,
                                        AtomicReference<List<ArticleCardVO>> articleCardsRef) {
    return Flux.create(sink -> {
        try {
            // Dispatcher 同步执行
            DispatcherNode dispatcher = new DispatcherNode(
                    chatModel, articleTool, bochaSearchTool, esVectorStore, redisComponent);
            Map<String, Object> dispatcherOutput = dispatcher.apply(state);

            @SuppressWarnings("unchecked")
            List<Map<String, String>> workerResults =
                    (List<Map<String, String>>) dispatcherOutput.getOrDefault("workerResults", List.of());
            @SuppressWarnings("unchecked")
            List<ArticleCardVO> cards =
                    (List<ArticleCardVO>) dispatcherOutput.getOrDefault("articleCards", List.of());
            articleCardsRef.set(cards);

            if (workerResults.size() <= 1) {
                // 虽然 Planner 判断多 Worker，但实际只有一个结果（可能某个 Worker 失败了）
                String result = workerResults.isEmpty() ? "抱歉，处理出错了"
                        : workerResults.get(0).get("result");
                streamByChunks(result, sink, fullReply);
            } else {
                // LLM 流式汇总
                streamSynthesize(userMessage, workerResults, sink, fullReply);
            }
        } catch (Exception e) {
            log.error("多Worker流式执行失败", e);
            sink.next("[ERROR] 处理失败");
            sink.complete();
        }
    });
}

/**
 * 创建支持流式的 Worker 实例
 */
private StreamableWorker createStreamableWorker(String workerName) {
    return switch (workerName) {
        case "search" -> new SearchWorkerNode(chatModel, articleTool, bochaSearchTool,
                esVectorStore, redisComponent);
        case "analysis" -> new AnalysisWorkerNode(chatModel, articleTool);
        case "writing" -> new WritingWorkerNode(chatModel);
        case "chat" -> new ChatWorkerNode(chatModel);
        default -> throw new IllegalArgumentException("未知的Worker: " + workerName);
    };
}
```

> **streamByChunks 和 streamSynthesize 方法与方案A完全一致**，此处不重复。

## 四、方案B的执行流程

### 4.1 单Worker场景："你好"

```
0s          ~1s                                    ~5s
│           │                                      │
▼           ▼                                      ▼
发送消息    Planner完成                             完成
            activeWorkers=["chat"]
            │
            ▼ 立即开始流式
            ChatWorkerNode.applyStream()
            │
            ├── "你" → "好！" → "有什" → "么可以" → "帮你的" → "吗？"
            │   （真正逐字流式，每个token实时发送）
            ▼
            流结束，保存回复
```

首字延迟：~1秒（只等 Planner）
方案A首字延迟：~3秒（等 Planner + Worker 同步完成 + 字符分片）

### 4.2 单Worker搜索场景："搜几篇Java文章"

```
0s          ~1s              ~2.5s                          ~6s
│           │                │                              │
▼           ▼                ▼                              ▼
发送消息    Planner完成      Tool执行完成                    完成
            activeWorkers    (搜索文章，这段时间前端无输出)
            =["search"]      │
                             ▼ Tool完成后开始流式
                             LLM整理搜索结果，逐字输出
                             ├── "找到" → "以下" → "文章：" → ...
                             ▼
                             流结束，获取文章卡片，__ARTICLES__
```

首字延迟：~2.5秒（Planner + Tool Calling）
方案A首字延迟：~4秒（Planner + Worker完全同步完成 + 字符分片）

### 4.3 多Worker场景："搜Java文章，顺便帮我列个大纲"

```
与方案A完全一致：
Planner(~1s) → Dispatcher同步执行(Worker并行, ~3s) → Synthesizer流式汇总(逐字输出)
首字延迟：~4秒
```

## 五、方案B的风险和注意事项

### 5.1 Tool Calling + 流式的兼容性

Spring AI 的 `.stream().content()` 在遇到 Tool Calling 时的行为：
- 框架会先同步执行 Tool（等待 Tool 返回结果）
- Tool 执行完后，把 Tool 结果注入到对话中，再流式调用 LLM 生成最终回复
- 所以 SearchWorkerNode 的流式不是"Tool 执行过程中就开始输出"，而是"Tool 执行完后才开始流式"

这意味着 SearchWorkerNode 的流式收益主要在 LLM 整理结果阶段（Tool 执行阶段仍然是同步等待）。

### 5.2 文章卡片获取时机

同步版本中，Worker 执行完后立即从 Redis 获取文章卡片。流式版本中，需要在 `doOnComplete` 回调中获取，确保 Tool 已经执行完毕并写入了 Redis。

### 5.3 Worker 代码重复

每个 Worker 的 `apply()` 和 `applyStream()` 方法有大量重复代码（构建 ChatClient、读取 taskDescriptions、构建 prompt 等）。可以通过提取公共方法来减少重复：

```java
// 提取公共的 prompt 构建逻辑
private ChatClient.PromptRequest buildPromptRequest(OverAllState state) {
    String taskInput = getTaskInput(state);
    ChatClient workerClient = ChatClient.builder(chatModel)
            .defaultSystem(CHAT_SYSTEM_PROMPT.formatted(java.time.LocalDate.now().toString()))
            .build();
    return workerClient.prompt().user(taskInput);
}

// 同步版本
@Override
public Map<String, Object> apply(OverAllState state) throws Exception {
    String result = buildPromptRequest(state).call().content();
    // ... 构建返回值
}

// 流式版本
@Override
public Flux<String> applyStream(OverAllState state) {
    return buildPromptRequest(state).stream().content();
}
```

### 5.4 降级场景

如果 Worker 的 `applyStream()` 抛异常，需要在 `streamSingleWorker` 中捕获并降级为错误提示：

```java
return worker.applyStream(state)
        .doOnNext(fullReply::append)
        .onErrorResume(e -> {
            log.error("Worker[{}]流式执行失败", workerName, e);
            return Flux.just("抱歉，处理出错了，请稍后重试");
        })
        .doOnComplete(() -> { ... });
```

## 六、从方案A升级到方案B的改动清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `agent/graph/node/StreamableWorker.java` | 流式 Worker 接口 |
| 修改 | `agent/graph/node/ChatWorkerNode.java` | 实现 StreamableWorker，新增 applyStream() |
| 修改 | `agent/graph/node/SearchWorkerNode.java` | 实现 StreamableWorker，新增 applyStream() |
| 修改 | `agent/graph/node/WritingWorkerNode.java` | 实现 StreamableWorker，新增 applyStream() |
| 修改 | `agent/graph/node/AnalysisWorkerNode.java` | 实现 StreamableWorker，新增 applyStream() |
| 修改 | `agent/service/AgentService.java` | chatStream 方法改为方案B逻辑 |
| 不动 | Graph 拓扑、Controller、前端 | 全部不变 |

## 七、建议

- 如果项目的主要场景是单 Worker（闲聊、搜索），方案B 的收益明显（首字延迟减半）
- 如果项目的主要场景是多 Worker 并行，方案B 和方案A 体验一致，不值得增加复杂度
- 建议先用方案A上线，收集用户反馈后再决定是否升级到方案B
- 方案B 的改动是增量的，不影响方案A 的非流式接口和 Graph 拓扑
