> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# Multi-Agent 协作模式改造方案（Orchestrator-Workers）

## 一、架构概述

### 1.1 当前架构（单Agent）

```
用户请求 → AgentService（单个ChatClient + 所有Tool） → 返回结果
```

问题：所有能力（搜索、分析、写作、闲聊）混在一个Agent里，system prompt臃肿，上下文窗口浪费，模型需要同时理解所有Tool的用法。

### 1.2 目标架构（Orchestrator-Workers）

```
用户请求
    │
    ▼
┌─────────────────────────────┐
│      OrchestratorAgent      │  主编排Agent（DeepSeek）
│  职责：                      │
│  1. 分析用户意图              │
│  2. 拆解为子任务              │
│  3. 按顺序/并行分配给Worker   │
│  4. 汇总Worker结果返回用户    │
└──────────┬──────────────────┘
           │ 拆解出子任务
     ┌─────┼─────┬──────────┐
     ▼     ▼     ▼          ▼
┌────────┐┌────────┐┌────────┐┌────────┐
│ Search ││Analysis││Writing ││  Chat  │
│ Worker ││ Worker ││ Worker ││ Worker │
│        ││        ││        ││        │
│搜索检索 ││深度分析 ││内容生成 ││日常问答 │
│有Tool   ││有Tool   ││纯LLM   ││纯LLM   │
└────────┘└────────┘└────────┘└────────┘
```

### 1.3 核心设计原则

- **上下文隔离**：每个Worker有独立的system prompt和上下文，不会互相污染
- **职责单一**：每个Worker只做一件事，prompt更精准，效果更好
- **Orchestrator不做具体工作**：只负责意图识别、任务拆解、结果汇总
- **Worker无状态**：Worker不持有会话历史，每次调用都是独立的任务执行
- **渐进式改造**：不改变现有的Controller、会话管理、前端，只改造AgentService内部

## 二、Worker定义

### 2.1 Worker注册表

每个Worker通过一个统一的数据结构描述，Orchestrator通过描述来决定委派给谁。

```java
package com.easyjob.agent.multiagent;

import lombok.Builder;
import lombok.Data;

/**
 * Worker定义
 * Orchestrator通过name和description来决定委派给哪个Worker
 */
@Data
@Builder
public class WorkerDefinition {
    /** Worker唯一标识 */
    private String name;
    /** Worker能力描述（给Orchestrator看的，用于意图匹配） */
    private String description;
}
```

### 2.2 四个Worker的定义

| Worker | name | description | 拥有的Tool | System Prompt 要点 |
|--------|------|-------------|-----------|-------------------|
| SearchWorker | search | 信息检索专家，负责搜索平台文章和联网搜索实时信息 | ArticleTool, BochaSearchTool | 你是搜索助手，只负责检索信息并返回结构化结果 |
| AnalysisWorker | analysis | 内容分析专家，负责阅读文章详情并进行深度分析、对比、总结 | ArticleTool(getArticleDetail) | 你是分析助手，基于提供的内容进行深度分析 |
| WritingWorker | writing | 写作助手，负责生成文章大纲、润色内容、提供写作建议 | 无（纯LLM） | 你是写作助手，擅长技术文章写作 |
| ChatWorker | chat | 日常对话和技术问答专家，处理闲聊、技术问题解答 | 无（纯LLM） | 你是博客平台的智能助手，友好地回答用户问题 |

## 三、核心代码改动

### 3.1 新增文件清单

```
src/main/java/com/easyjob/agent/multiagent/
├── WorkerDefinition.java          // Worker定义
├── WorkerRegistry.java            // Worker注册表
├── OrchestratorService.java       // 编排器核心逻辑
└── WorkerChatClientFactory.java   // Worker专用ChatClient工厂
```

### 3.2 WorkerRegistry — Worker注册表

```java
package com.easyjob.agent.multiagent;

import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Worker注册表
 * 启动时注册所有可用Worker，供Orchestrator查询
 */
@Component
public class WorkerRegistry {

    private final Map<String, WorkerDefinition> workers = new LinkedHashMap<>();

    @PostConstruct
    public void init() {
        register(WorkerDefinition.builder()
                .name("search")
                .description("信息检索专家。负责搜索平台上的文章（关键词搜索、语义搜索）和联网搜索实时信息（新闻、热点、天气等）。当用户想找文章、查资料、了解最新动态时使用。")
                .build());

        register(WorkerDefinition.builder()
                .name("analysis")
                .description("内容分析专家。负责阅读文章详情并进行深度分析、对比、总结。当需要深入理解某篇文章内容、对比多篇文章、提取关键信息时使用。需要先由search找到文章ID。")
                .build());

        register(WorkerDefinition.builder()
                .name("writing")
                .description("写作助手。负责生成文章大纲、润色内容、提供写作建议、改写文本。当用户需要写作帮助时使用。")
                .build());

        register(WorkerDefinition.builder()
                .name("chat")
                .description("日常对话和技术问答专家。处理闲聊、技术问题解答、编程知识、概念解释等。当用户的问题不涉及搜索、分析或写作时使用。")
                .build());
    }

    public void register(WorkerDefinition worker) {
        workers.put(worker.getName(), worker);
    }

    public WorkerDefinition getWorker(String name) {
        return workers.get(name);
    }

    public List<WorkerDefinition> getAllWorkers() {
        return List.copyOf(workers.values());
    }

    /**
     * 生成Worker描述文本（注入到Orchestrator的system prompt中）
     */
    public String buildWorkerCatalog() {
        StringBuilder sb = new StringBuilder();
        for (WorkerDefinition w : workers.values()) {
            sb.append(String.format("- %s: %s\n", w.getName(), w.getDescription()));
        }
        return sb.toString();
    }
}
```

### 3.3 WorkerChatClientFactory — Worker专用ChatClient工厂

```java
package com.easyjob.agent.multiagent;

import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.entity.DocumentChunk;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import lombok.extern.slf4j.Slf4j;

import java.util.List;

/**
 * Worker专用ChatClient工厂
 * 每个Worker有独立的system prompt和tool配置
 * 每次调用创建新的ChatClient实例，保证上下文隔离
 *
 * 【RAG集成】SearchWorker内置RAG检索能力，在创建时自动注入检索结果
 */
@Slf4j
@Component
public class WorkerChatClientFactory {

    @Autowired
    private DeepSeekChatModel deepSeekChatModel;
    @Autowired
    private ArticleTool articleTool;
    @Autowired
    private BochaSearchTool bochaSearchTool;
    @Autowired
    private EsVectorStore esVectorStore;

    @Value("${agent.rag.enabled:true}")
    private boolean ragEnabled;

    @Value("${agent.rag.top-k:5}")
    private int ragTopK;

    @Value("${agent.rag.similarity-threshold:0.7}")
    private float ragThreshold;

    private static final String SEARCH_SYSTEM_PROMPT = """
            你是一个信息检索助手，专门负责搜索和检索信息。
            
            【职责】
            - 根据任务描述，使用工具搜索平台文章或联网搜索实时信息
            - 返回结构化的搜索结果，包含标题、摘要、关键信息
            - 不要对搜索结果做过多分析，只负责检索和整理
            
            【当前日期】%s
            
            【输出要求】
            - 直接返回搜索结果，不要添加多余的开场白
            - 保持结果简洁、结构化
            - 不要把文章id露出来
            """;

    private static final String ANALYSIS_SYSTEM_PROMPT = """
            你是一个内容分析专家，专门负责深度分析文章内容。
            
            【职责】
            - 阅读文章详情，提取关键信息
            - 对比多篇文章的异同
            - 总结核心观点和技术要点
            - 给出专业的分析见解
            
            【输出要求】
            - 分析要有深度，不要流于表面
            - 结构化输出，使用标题和列表
            - 引用具体的文章内容作为依据
            """;

    private static final String WRITING_SYSTEM_PROMPT = """
            你是一个技术写作助手，专门负责内容创作和写作辅助。
            
            【职责】
            - 生成文章大纲和结构建议
            - 润色和改写文本内容
            - 提供写作建议和改进方向
            - 帮助组织和优化文章逻辑
            
            【输出要求】
            - 写作风格专业但易读
            - 技术内容准确
            - 结构清晰，逻辑连贯
            """;

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

    /**
     * 创建指定Worker的ChatClient
     * 每次调用都创建新实例，保证上下文隔离
     *
     * @param workerName Worker名称
     * @param taskInput  任务输入（SearchWorker用于RAG检索）
     */
    public ChatClient createWorkerClient(String workerName, String taskInput) {
        String today = java.time.LocalDate.now().toString();

        return switch (workerName) {
            case "search" -> {
                // SearchWorker：system prompt中注入RAG检索结果
                String ragContext = retrieveRagContext(taskInput);
                String systemPrompt = SEARCH_SYSTEM_PROMPT.formatted(today);
                if (!ragContext.isEmpty()) {
                    systemPrompt += "\n\n【RAG参考资料】以下是与任务相关的平台文章片段，可作为参考：\n" + ragContext;
                }
                yield ChatClient.builder(deepSeekChatModel)
                        .defaultSystem(systemPrompt)
                        .build();
            }
            case "analysis" -> ChatClient.builder(deepSeekChatModel)
                    .defaultSystem(ANALYSIS_SYSTEM_PROMPT)
                    .build();
            case "writing" -> ChatClient.builder(deepSeekChatModel)
                    .defaultSystem(WRITING_SYSTEM_PROMPT)
                    .build();
            case "chat" -> ChatClient.builder(deepSeekChatModel)
                    .defaultSystem(CHAT_SYSTEM_PROMPT.formatted(today))
                    .build();
            default -> throw new IllegalArgumentException("未知的Worker: " + workerName);
        };
    }

    /**
     * 获取Worker对应的Tool列表
     * 返回null表示该Worker不需要Tool
     */
    public Object[] getWorkerTools(String workerName) {
        return switch (workerName) {
            case "search" -> new Object[]{articleTool, bochaSearchTool};
            case "analysis" -> new Object[]{articleTool};
            case "writing", "chat" -> null;  // 纯LLM，无Tool
            default -> null;
        };
    }

    /**
     * RAG检索（仅SearchWorker使用）
     * 从原AgentService.retrieveContext迁移过来
     */
    private String retrieveRagContext(String query) {
        if (!ragEnabled || query == null || query.isBlank()) {
            return "";
        }
        try {
            List<DocumentChunk> chunks = esVectorStore.search(query, ragTopK, ragThreshold);
            if (chunks.isEmpty()) {
                return "";
            }
            StringBuilder context = new StringBuilder();
            for (int i = 0; i < chunks.size(); i++) {
                DocumentChunk chunk = chunks.get(i);
                if (chunk.getContent() == null || chunk.getContent().isBlank()) {
                    continue;
                }
                context.append(String.format("【参考%d】来自《%s》:\n%s\n\n",
                        i + 1, chunk.getTitle(), chunk.getContent()));
            }
            log.info("SearchWorker RAG检索完成, query长度: {}, 结果数: {}", query.length(), chunks.size());
            return context.toString();
        } catch (Exception e) {
            log.error("SearchWorker RAG检索失败", e);
            return "";
        }
    }
}
```


### 3.4 OrchestratorService — 编排器核心

这是整个 Multi-Agent 架构的核心。Orchestrator 自身也是一个 Agent（有自己的 ChatClient），它的职责是：
1. 接收用户请求 + 历史上下文
2. 调用 LLM 分析意图，输出结构化的任务计划（JSON）
3. 按计划依次调用 Worker 执行子任务
4. 汇总所有 Worker 的结果，生成最终回复

```java
package com.easyjob.agent.multiagent;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.component.RedisComponent;
import com.easyjob.vo.ArticleCardVO;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
public class OrchestratorService {

    @Autowired
    private DeepSeekChatModel deepSeekChatModel;
    @Autowired
    private WorkerRegistry workerRegistry;
    @Autowired
    private WorkerChatClientFactory workerClientFactory;
    @Autowired
    private RedisComponent redisComponent;

    /**
     * Orchestrator的system prompt
     * 核心：告诉LLM有哪些Worker可用，要求输出结构化的任务计划
     */
    private String buildOrchestratorPrompt() {
        String workerCatalog = workerRegistry.buildWorkerCatalog();
        return """
                你是一个任务编排器（Orchestrator），负责分析用户请求并拆解为子任务。
                
                【可用的Worker】
                %s
                
                【你的职责】
                1. 分析用户的意图
                2. 决定需要哪些Worker来完成任务
                3. 输出一个JSON格式的任务计划
                
                【输出格式】严格输出以下JSON，不要输出其他内容：
                ```json
                {
                  "tasks": [
                    {
                      "worker": "worker名称",
                      "task": "给这个worker的具体任务描述",
                      "dependsOn": []
                    }
                  ]
                }
                ```
                
                【规则】
                - tasks数组中的任务按执行顺序排列
                - dependsOn表示依赖的前置任务索引（从0开始），空数组表示无依赖
                - 简单问题（闲聊、单一搜索）只需要一个task
                - 复杂问题才需要多个task协作
                - 每个task的"task"字段要写清楚具体要做什么，包含必要的上下文信息
                - 如果后续task依赖前面的结果，在task描述中说明"基于前面的搜索结果..."即可
                
                【示例1】用户："帮我搜几篇Java并发的文章"
                ```json
                {
                  "tasks": [
                    {"worker": "search", "task": "搜索平台上关于Java并发的文章", "dependsOn": []}
                  ]
                }
                ```
                
                【示例2】用户："帮我了解下Spring Boot最新特性，结合平台文章总结下"
                ```json
                {
                  "tasks": [
                    {"worker": "search", "task": "联网搜索Spring Boot最新版本的新特性", "dependsOn": []},
                    {"worker": "search", "task": "搜索平台上关于Spring Boot的文章", "dependsOn": []},
                    {"worker": "analysis", "task": "基于前面的搜索结果，对比分析Spring Boot最新特性和平台文章的覆盖情况，总结关键信息", "dependsOn": [0, 1]}
                  ]
                }
                ```
                
                【示例3】用户："今天天气怎么样"
                ```json
                {
                  "tasks": [
                    {"worker": "search", "task": "联网搜索今天的天气信息", "dependsOn": []}
                  ]
                }
                ```
                """.formatted(workerCatalog);
    }

    /**
     * 编排执行入口
     *
     * @param messages    包含历史上下文 + 当前用户消息的完整消息列表
     * @param conversationId 会话ID（传递给Tool用）
     * @return 最终回复文本
     */
    public OrchestratorResult orchestrate(List<Message> messages, Long conversationId) {
        // 1. 调用Orchestrator LLM，生成任务计划
        List<TaskPlan> taskPlans = planTasks(messages);
        log.info("Orchestrator任务计划: {}", JSON.toJSONString(taskPlans));

        // 2. 按依赖顺序执行Worker
        List<WorkerResult> workerResults = executeTasks(taskPlans, conversationId);

        // 3. 如果只有一个Worker且是chat/writing，直接返回Worker结果
        if (taskPlans.size() == 1) {
            String workerName = taskPlans.get(0).getWorker();
            if ("chat".equals(workerName) || "writing".equals(workerName)) {
                // 从Redis获取文章卡片（虽然chat/writing一般没有，但保持一致）
                List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(conversationId);
                return new OrchestratorResult(workerResults.get(0).getResult(), cards);
            }
        }

        // 4. 多Worker结果需要汇总
        String finalReply = synthesize(messages, workerResults);

        // 5. 获取文章卡片
        List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(conversationId);

        return new OrchestratorResult(finalReply, cards);
    }

    /**
     * 第一步：调用LLM生成任务计划
     */
    private List<TaskPlan> planTasks(List<Message> messages) {
        ChatClient orchestratorClient = ChatClient.builder(deepSeekChatModel)
                .defaultSystem(buildOrchestratorPrompt())
                .build();

        String planJson = orchestratorClient.prompt()
                .messages(messages)
                .call()
                .content();

        return parseTaskPlans(planJson);
    }

    /**
     * 第二步：按依赖顺序执行Worker
     */
    private List<WorkerResult> executeTasks(List<TaskPlan> taskPlans, Long conversationId) {
        List<WorkerResult> results = new ArrayList<>();

        for (int i = 0; i < taskPlans.size(); i++) {
            TaskPlan plan = taskPlans.get(i);

            // 构建Worker的输入：任务描述 + 前置任务的结果
            StringBuilder workerInput = new StringBuilder();
            workerInput.append("【任务】").append(plan.getTask()).append("\n");

            // 注入依赖任务的结果
            if (plan.getDependsOn() != null && !plan.getDependsOn().isEmpty()) {
                workerInput.append("\n【前置任务结果】\n");
                for (int depIdx : plan.getDependsOn()) {
                    if (depIdx < results.size()) {
                        WorkerResult depResult = results.get(depIdx);
                        workerInput.append(String.format("[%s的结果]: %s\n",
                                depResult.getWorkerName(), depResult.getResult()));
                    }
                }
            }

            // 调用Worker
            String result = executeWorker(plan.getWorker(), workerInput.toString(), conversationId);
            results.add(new WorkerResult(plan.getWorker(), plan.getTask(), result));

            log.info("Worker[{}] 执行完成, 任务: {}, 结果长度: {}",
                    plan.getWorker(), plan.getTask(), result.length());
        }

        return results;
    }

    /**
     * 调用单个Worker执行任务（非流式）
     */
    private String executeWorker(String workerName, String taskInput, Long conversationId) {
        // 传入taskInput用于SearchWorker的RAG检索
        ChatClient workerClient = workerClientFactory.createWorkerClient(workerName, taskInput);
        Object[] tools = workerClientFactory.getWorkerTools(workerName);

        try {
            if (tools != null && tools.length > 0) {
                return workerClient.prompt()
                        .user(taskInput)
                        .tools(tools)
                        .toolContext(Map.of("conversationId", conversationId))
                        .call()
                        .content();
            } else {
                return workerClient.prompt()
                        .user(taskInput)
                        .call()
                        .content();
            }
        } catch (Exception e) {
            log.error("Worker[{}] 执行失败", workerName, e);
            throw new RuntimeException("Worker[" + workerName + "]执行失败: " + e.getMessage(), e);
        }
    }

    /**
     * 调用单个Worker执行任务（流式）
     * 仅用于单Worker场景的真正流式输出
     */
    public Flux<String> executeWorkerStream(String workerName, String taskInput, Long conversationId) {
        ChatClient workerClient = workerClientFactory.createWorkerClient(workerName, taskInput);
        Object[] tools = workerClientFactory.getWorkerTools(workerName);

        if (tools != null && tools.length > 0) {
            return workerClient.prompt()
                    .user(taskInput)
                    .tools(tools)
                    .toolContext(Map.of("conversationId", conversationId))
                    .stream()
                    .content();
        } else {
            return workerClient.prompt()
                    .user(taskInput)
                    .stream()
                    .content();
        }
    }

    /**
     * 汇总阶段的流式输出
     * 用于多Worker场景：Worker同步执行完毕后，汇总阶段流式返回
     */
    public Flux<String> synthesizeStream(List<Message> messages, List<WorkerResult> workerResults) {
        ChatClient synthesizer = ChatClient.builder(deepSeekChatModel)
                .defaultSystem("""
                        你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。
                        
                        【要求】
                        - 不要简单拼接，要有逻辑地组织内容
                        - 保留关键信息，去除重复内容
                        - 使用清晰的结构（标题、列表等）
                        - 语言自然流畅，像是一个人在回答
                        - 不要提及"Worker"、"任务"等内部概念
                        """)
                .build();

        StringBuilder synthInput = new StringBuilder();
        for (int i = messages.size() - 1; i >= 0; i--) {
            if (messages.get(i) instanceof UserMessage) {
                synthInput.append("【用户问题】").append(((UserMessage) messages.get(i)).getText()).append("\n\n");
                break;
            }
        }
        synthInput.append("【各专家的工作结果】\n");
        for (WorkerResult wr : workerResults) {
            synthInput.append(String.format("\n--- %s ---\n%s\n", wr.getWorkerName(), wr.getResult()));
        }

        return synthesizer.prompt()
                .user(synthInput.toString())
                .stream()
                .content();
    }

    /**
     * 暴露planTasks给AgentService用（流式场景需要先拿到任务计划再决定走哪条路）
     */
    public List<TaskPlan> planTasksPublic(List<Message> messages) {
        return planTasks(messages);
    }

    /**
     * 暴露executeTasks给AgentService用
     */
    public List<WorkerResult> executeTasksPublic(List<TaskPlan> taskPlans, Long conversationId) {
        return executeTasks(taskPlans, conversationId);
    }

    /**
     * 第三步：汇总多个Worker的结果
     */
    private String synthesize(List<Message> messages, List<WorkerResult> workerResults) {
        ChatClient synthesizer = ChatClient.builder(deepSeekChatModel)
                .defaultSystem("""
                        你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。
                        
                        【要求】
                        - 不要简单拼接，要有逻辑地组织内容
                        - 保留关键信息，去除重复内容
                        - 使用清晰的结构（标题、列表等）
                        - 语言自然流畅，像是一个人在回答
                        - 不要提及"Worker"、"任务"等内部概念
                        """)
                .build();

        // 构建汇总输入
        StringBuilder synthInput = new StringBuilder();
        // 提取用户原始问题（最后一条UserMessage）
        for (int i = messages.size() - 1; i >= 0; i--) {
            if (messages.get(i) instanceof UserMessage) {
                synthInput.append("【用户问题】").append(((UserMessage) messages.get(i)).getText()).append("\n\n");
                break;
            }
        }
        synthInput.append("【各专家的工作结果】\n");
        for (WorkerResult wr : workerResults) {
            synthInput.append(String.format("\n--- %s ---\n%s\n", wr.getWorkerName(), wr.getResult()));
        }

        return synthesizer.prompt()
                .user(synthInput.toString())
                .call()
                .content();
    }

    /**
     * 解析LLM输出的任务计划JSON
     * 包含重试机制：首次解析失败时，用LLM修正JSON后再解析一次
     */
    private List<TaskPlan> parseTaskPlans(String planJson) {
        // 第一次尝试解析
        try {
            return doParseTaskPlans(planJson);
        } catch (Exception e) {
            log.warn("首次解析任务计划失败，尝试LLM修正, 原始输出: {}", planJson);
        }

        // 第二次：用LLM修正JSON格式
        try {
            ChatClient fixClient = ChatClient.builder(deepSeekChatModel)
                    .defaultSystem("你是一个JSON修正助手。用户会给你一段可能格式不正确的JSON，请修正并只输出正确的JSON，不要输出其他内容。")
                    .build();

            String fixedJson = fixClient.prompt()
                    .user("请修正以下JSON，使其符合格式 {\"tasks\": [{\"worker\": \"名称\", \"task\": \"描述\", \"dependsOn\": []}]}：\n\n" + planJson)
                    .call()
                    .content();

            return doParseTaskPlans(fixedJson);
        } catch (Exception e2) {
            log.error("LLM修正后仍然解析失败，降级为chat处理, 原始输出: {}", planJson, e2);
            // 最终降级：提取用户原始问题，交给chat处理
            TaskPlan fallback = new TaskPlan();
            fallback.setWorker("chat");
            fallback.setTask("请直接回答用户的问题");
            fallback.setDependsOn(new ArrayList<>());
            return List.of(fallback);
        }
    }

    /**
     * 实际的JSON解析逻辑（从parseTaskPlans中抽取，复用）
     */
    private List<TaskPlan> doParseTaskPlans(String planJson) {
        // 提取JSON（LLM可能会包裹在```json...```中）
        String json = planJson;
        if (json.contains("```json")) {
            json = json.substring(json.indexOf("```json") + 7);
            json = json.substring(0, json.indexOf("```"));
        } else if (json.contains("```")) {
            json = json.substring(json.indexOf("```") + 3);
            json = json.substring(0, json.indexOf("```"));
        }
        json = json.trim();

        JSONObject obj = JSON.parseObject(json);
        JSONArray tasksArray = obj.getJSONArray("tasks");

        if (tasksArray == null || tasksArray.isEmpty()) {
            throw new IllegalArgumentException("tasks数组为空");
        }

        List<TaskPlan> plans = new ArrayList<>();
        for (int i = 0; i < tasksArray.size(); i++) {
            JSONObject taskObj = tasksArray.getJSONObject(i);
            TaskPlan plan = new TaskPlan();
            plan.setWorker(taskObj.getString("worker"));
            plan.setTask(taskObj.getString("task"));

            // 校验worker名称是否合法
            if (workerRegistry.getWorker(plan.getWorker()) == null) {
                throw new IllegalArgumentException("未知的Worker: " + plan.getWorker());
            }

            JSONArray deps = taskObj.getJSONArray("dependsOn");
            if (deps != null) {
                plan.setDependsOn(deps.toJavaList(Integer.class));
            } else {
                plan.setDependsOn(new ArrayList<>());
            }
            plans.add(plan);
        }
        return plans;
    }

    // ========== 内部数据类 ==========

    @Data
    public static class TaskPlan {
        private String worker;
        private String task;
        private List<Integer> dependsOn;
    }

    @Data
    public static class WorkerResult {
        private String workerName;
        private String task;
        private String result;

        public WorkerResult(String workerName, String task, String result) {
            this.workerName = workerName;
            this.task = task;
            this.result = result;
        }
    }

    @Data
    public static class OrchestratorResult {
        private String reply;
        private List<ArticleCardVO> articleCards;

        public OrchestratorResult(String reply, List<ArticleCardVO> articleCards) {
            this.reply = reply;
            this.articleCards = articleCards;
        }
    }
}
```


### 3.5 改造 AgentService

原有的 `AgentService` 改为调用 `OrchestratorService`，不再直接持有 Tool 和 ChatClient。

#### 3.5.1 改造后的 chat 方法（非流式）

```java
@Autowired
private OrchestratorService orchestratorService;

/**
 * 非流式聊天 - 通过Orchestrator编排多Agent协作
 */
public AiChatVO chat(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
    // 1. 创建或获取会话
    final Long finalConvId;
    if (conversationId == null) {
        finalConvId = aiConversationService.createConversation(userId);
    } else {
        finalConvId = conversationId;
    }

    // 2. 图片转文字
    String processedMessage = preprocessMessage(userMessage, imagePaths);

    // 3. 构建历史消息（只包含历史上下文 + 当前消息，不含system prompt）
    List<Message> messages = buildContextMessages(finalConvId, processedMessage);

    // 4. 保存用户消息
    aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);

    // 5. 调用Orchestrator编排执行
    OrchestratorService.OrchestratorResult result = orchestratorService.orchestrate(messages, finalConvId);

    // 6. 保存AI回复
    aiConversationService.addMessage(finalConvId, userId, "assistant", result.getReply(), null, result.getArticleCards());

    return AiChatVO.builder()
            .conversationId(String.valueOf(finalConvId))
            .reply(result.getReply())
            .articles(result.getArticleCards())
            .build();
}
```

#### 3.5.2 改造后的 buildContextMessages 方法

```java
/**
 * 构建上下文消息列表（不含system prompt，由各Worker自带）
 * 只包含历史对话 + 当前用户消息
 */
private List<Message> buildContextMessages(Long conversationId, String userMessage) {
    List<Message> messages = new ArrayList<>();

    // 历史上下文
    List<AiMessage> history = aiConversationService.getContext(conversationId);
    for (AiMessage msg : history) {
        if ("user".equals(msg.getRole())) {
            messages.add(new UserMessage(msg.getContent()));
        } else if ("assistant".equals(msg.getRole())) {
            messages.add(new AssistantMessage(msg.getContent()));
        }
    }

    // 当前用户消息
    messages.add(new UserMessage(userMessage));
    return messages;
}
```

#### 3.5.3 改造后的 chatStream（真正流式）

流式场景的核心策略：
- 单Worker（chat/writing）：直接走Worker的stream方法，真正逐字输出
- 单Worker（search/analysis，有Tool）：Tool Calling不支持流式，同步执行后一次性返回
- 多Worker：同步执行所有Worker，汇总阶段走stream流式输出

```java
/**
 * 流式聊天 - Multi-Agent版本
 *
 * 策略：
 * - 单Worker且无Tool（chat/writing）：真正流式输出
 * - 单Worker有Tool（search/analysis）：同步执行，结果一次性返回
 * - 多Worker：同步执行所有Worker，汇总阶段流式输出
 */
public Flux<String> chatStream(Long conversationId, Long userId, String userMessage, List<String> imagePaths) {
    // 1. 创建或获取会话
    final Long finalConvId;
    if (conversationId == null) {
        finalConvId = aiConversationService.createConversation(userId);
    } else {
        finalConvId = conversationId;
    }

    // 2. 图片转文字
    String processedMessage = preprocessMessage(userMessage, imagePaths);

    // 3. 构建历史消息
    List<Message> messages = buildContextMessages(finalConvId, processedMessage);

    // 4. 保存用户消息
    aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);

    // 5. 同步获取任务计划（这一步必须同步，因为要根据计划决定走哪条路）
    List<OrchestratorService.TaskPlan> taskPlans = orchestratorService.planTasksPublic(messages);
    log.info("流式模式 - 任务计划: {}", JSON.toJSONString(taskPlans));

    StringBuilder fullReply = new StringBuilder();
    final AtomicReference<List<ArticleCardVO>> articleCardsRef = new AtomicReference<>(new ArrayList<>());

    // 6. 根据任务计划选择流式策略
    if (taskPlans.size() == 1) {
        OrchestratorService.TaskPlan singleTask = taskPlans.get(0);
        String workerName = singleTask.getWorker();
        String taskInput = "【任务】" + singleTask.getTask();
        boolean hasTools = ("search".equals(workerName) || "analysis".equals(workerName));

        if (!hasTools) {
            // ===== 单Worker无Tool：真正流式 =====
            return Flux.concat(
                    Flux.just("__CONV_ID__:" + finalConvId),
                    orchestratorService.executeWorkerStream(workerName, taskInput, finalConvId)
                            .doOnNext(fullReply::append)
                            .doOnComplete(() -> {
                                List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
                                articleCardsRef.set(cards);
                                aiConversationService.addMessage(finalConvId, userId, "assistant",
                                        fullReply.toString(), null,
                                        cards.isEmpty() ? null : cards);
                            }),
                    Flux.defer(() -> {
                        List<ArticleCardVO> cards = articleCardsRef.get();
                        if (cards != null && !cards.isEmpty()) {
                            return Flux.just("__ARTICLES__:" + JSON.toJSONString(cards));
                        }
                        return Flux.empty();
                    })
            );
        } else {
            // ===== 单Worker有Tool：同步执行，结果一次性返回 =====
            return Flux.concat(
                    Flux.just("__CONV_ID__:" + finalConvId),
                    Flux.defer(() -> {
                        List<OrchestratorService.WorkerResult> results =
                                orchestratorService.executeTasksPublic(taskPlans, finalConvId);
                        String reply = results.get(0).getResult();
                        fullReply.append(reply);

                        List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
                        articleCardsRef.set(cards);
                        aiConversationService.addMessage(finalConvId, userId, "assistant",
                                reply, null, cards.isEmpty() ? null : cards);

                        return Flux.just(reply);
                    }),
                    Flux.defer(() -> {
                        List<ArticleCardVO> cards = articleCardsRef.get();
                        if (cards != null && !cards.isEmpty()) {
                            return Flux.just("__ARTICLES__:" + JSON.toJSONString(cards));
                        }
                        return Flux.empty();
                    })
            );
        }
    }

    // ===== 多Worker：同步执行Worker，汇总阶段流式输出 =====
    return Flux.concat(
            Flux.just("__CONV_ID__:" + finalConvId),
            Flux.defer(() -> {
                // 同步执行所有Worker
                List<OrchestratorService.WorkerResult> workerResults =
                        orchestratorService.executeTasksPublic(taskPlans, finalConvId);

                // 汇总阶段流式输出
                return orchestratorService.synthesizeStream(messages, workerResults)
                        .doOnNext(fullReply::append);
            }).doOnComplete(() -> {
                List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(finalConvId);
                articleCardsRef.set(cards);
                aiConversationService.addMessage(finalConvId, userId, "assistant",
                        fullReply.toString(), null,
                        cards.isEmpty() ? null : cards);
            }),
            Flux.defer(() -> {
                List<ArticleCardVO> cards = articleCardsRef.get();
                if (cards != null && !cards.isEmpty()) {
                    return Flux.just("__ARTICLES__:" + JSON.toJSONString(cards));
                }
                return Flux.empty();
            })
    );
}
```

> **流式策略总结**：
> - chat/writing 单任务：用户体验最好，真正逐字输出，零等待
> - search/analysis 单任务：有Tool Calling，必须同步等待Tool执行完，结果一次性返回
> - 多Worker协作：Worker阶段同步等待（用户会有等待期），汇总阶段逐字流式输出

### 3.6 删除 AgentService 中不再需要的依赖

改造后，`AgentService` 不再直接依赖以下内容（移到 Worker 层）：

```java
// 删除这些字段（已移到WorkerChatClientFactory和OrchestratorService）
// @Autowired private ChatClient chatClient;
// @Autowired private ArticleTool articleTool;
// @Autowired private BochaSearchTool bochaSearchTool;
// @Autowired private EsVectorStore esVectorStore;
// RAG相关配置也移除（RAG由SearchWorker内部处理，或保留在buildMessages中）

// 保留的依赖
@Autowired private AiConversationService aiConversationService;
@Autowired private OrchestratorService orchestratorService;
@Autowired private ImageUnderstandingService imageService;
@Autowired private RedisComponent redisComponent;
```

### 3.7 RAG 的处理

RAG 检索逻辑已从 `AgentService.buildMessages()` 迁移到 `WorkerChatClientFactory` 内部。

当 SearchWorker 被创建时，工厂方法会根据任务输入自动执行 RAG 检索，将检索结果注入到 SearchWorker 的 system prompt 中。其他 Worker（analysis/writing/chat）不触发 RAG，避免无关检索浪费资源。

原 `AgentService` 中的以下代码可以删除：
```java
// 删除：RAG相关字段
// @Autowired private EsVectorStore esVectorStore;
// @Value("${agent.rag.enabled:true}") private boolean ragEnabled;
// @Value("${agent.rag.top-k:5}") private int ragTopK;
// @Value("${agent.rag.similarity-threshold:0.7}") private float ragThreshold;

// 删除：retrieveContext方法（已迁移到WorkerChatClientFactory.retrieveRagContext）
// 删除：buildMessages中的RAG注入逻辑
```

## 四、ChatClientConfiguration 改动

原有的 `chatClient` Bean 不再作为主对话客户端使用（Worker 各自创建），但可以保留给其他地方用，或者删除。

```java
@Configuration
public class ChatClientConfiguration {

    /**
     * 【保留】智谱视觉模型客户端（图片理解，不受Multi-Agent影响）
     */
    @Bean("zhipuVisionClient")
    public ChatClient zhipuVisionClient(ZhiPuAiChatModel zhiPuAiChatModel) {
        return ChatClient.builder(zhiPuAiChatModel)
                .defaultSystem(ZHIPU_VISION_SYSTEM_PROMPT)
                .build();
    }

    // 原有的 chatClient Bean 可以删除，或改名为备用
    // Worker的ChatClient由WorkerChatClientFactory动态创建
}
```

## 五、执行流程详解

### 5.1 简单场景：用户说"你好"

```
1. Orchestrator收到消息
2. 调用LLM分析 → 输出: {"tasks": [{"worker": "chat", "task": "回复用户的问候", "dependsOn": []}]}
3. 只有1个task且是chat → 直接调用ChatWorker
4. ChatWorker返回结果 → 直接作为最终回复（不经过汇总）
```

LLM调用次数：2次（Orchestrator规划1次 + ChatWorker执行1次）

### 5.2 简单场景：用户说"搜几篇Java文章"

```
1. Orchestrator收到消息
2. 调用LLM分析 → 输出: {"tasks": [{"worker": "search", "task": "搜索Java相关文章", "dependsOn": []}]}
3. 只有1个task → 调用SearchWorker（带ArticleTool）
4. SearchWorker调用searchArticles Tool → 返回搜索结果
5. 单Worker结果直接返回（经过汇总LLM润色）
```

LLM调用次数：3次（Orchestrator规划1次 + SearchWorker执行1次 + 汇总1次）

### 5.3 复杂场景：用户说"帮我了解Spring Boot最新特性，结合平台文章总结"

```
1. Orchestrator收到消息
2. 调用LLM分析 → 输出:
   {"tasks": [
     {"worker": "search", "task": "联网搜索Spring Boot最新特性", "dependsOn": []},
     {"worker": "search", "task": "搜索平台上Spring Boot相关文章", "dependsOn": []},
     {"worker": "analysis", "task": "基于搜索结果进行对比分析", "dependsOn": [0, 1]}
   ]}
3. 执行task[0]: SearchWorker联网搜索 → 结果A
4. 执行task[1]: SearchWorker平台搜索 → 结果B
5. 执行task[2]: AnalysisWorker收到(结果A + 结果B) → 分析结果C
6. 汇总LLM整合所有结果 → 最终回复
```

LLM调用次数：5次（规划1 + Worker执行3 + 汇总1）

### 5.4 关于LLM调用次数的说明

Multi-Agent 模式相比单 Agent 会增加 LLM 调用次数（至少多一次 Orchestrator 规划）。这是架构复杂度换来的好处：
- 每个 Worker 的 prompt 更精准，回答质量更高
- 上下文窗口利用更高效（Worker 不需要加载无关的 Tool 定义）
- 复杂任务的处理能力显著提升

对于简单任务（闲聊），可以考虑加一个"快速通道"优化：在 Orchestrator 规划前先做一次轻量级意图判断，如果是简单闲聊直接跳过规划，走 ChatWorker。这个优化后续再做。

## 六、文件改动总结

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `agent/multiagent/WorkerDefinition.java` | Worker定义数据类 |
| 新增 | `agent/multiagent/WorkerRegistry.java` | Worker注册表 |
| 新增 | `agent/multiagent/WorkerChatClientFactory.java` | Worker ChatClient工厂 |
| 新增 | `agent/multiagent/OrchestratorService.java` | 编排器核心 |
| 修改 | `agent/service/AgentService.java` | 改为调用OrchestratorService |
| 修改 | `agent/config/ChatClientConfiguration.java` | 删除主chatClient Bean |
| 不动 | `agent/tool/ArticleTool.java` | Tool不变，被Worker引用 |
| 不动 | `agent/tool/BochaSearchTool.java` | Tool不变，被Worker引用 |
| 不动 | `agent/controller/AgentController.java` | Controller不变 |
| 不动 | `agent/service/AiConversationService.java` | 会话管理不变 |
| 不动 | 前端所有文件 | 前端不需要改动 |

## 七、注意事项

1. **JSON解析三级保障**：第一次直接解析 → 失败后用LLM修正JSON再解析 → 仍失败则降级为chat处理。生产环境中DeepSeek对JSON格式的遵循度较高，大部分情况第一次就能成功
2. **Worker名称校验**：`doParseTaskPlans` 中会校验worker名称是否在注册表中，防止LLM幻觉出不存在的Worker
3. **Worker上下文隔离**：每次调用 `createWorkerClient` 都创建新实例。`ChatClient.builder()` 是轻量操作（只是配置组装），真正的开销在LLM调用上，所以不用担心性能
4. **Tool的conversationId传递**：通过 `toolContext` 传递，与现有 ArticleTool 的实现兼容，不需要改Tool代码
5. **流式策略**：chat/writing单任务走真正流式（逐字输出），search/analysis单任务同步执行后一次性返回，多Worker协作时Worker阶段同步+汇总阶段流式
6. **RAG只在SearchWorker触发**：避免闲聊、写作等场景做无意义的向量检索，节省资源
7. **成本控制**：每次请求至少2次LLM调用（规划+执行），复杂任务可能5+次。如果成本敏感，可以对Orchestrator规划阶段使用更便宜的模型
8. **后续优化方向**：可以加"快速通道"——在Orchestrator规划前做轻量级意图分类（基于关键词规则而非LLM），简单闲聊直接跳过规划走ChatWorker，省掉一次LLM调用
