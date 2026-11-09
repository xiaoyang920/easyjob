> 历史归档：本文包含已移除的 Java Agent 实现，仅供学习参考。当前结构见[运行架构](../../architecture/current-runtime.md)。

# Multi-Agent 并行协作方案（Spring AI Alibaba Graph）

> 本文档是 `11-multi-agent-orchestrator.md`（手写编排方案）的替代方案，使用 Spring AI Alibaba 提供的 Graph 框架实现 **并行 Multi-Agent** 架构。
> 
> 与旧版文档的核心区别：旧版是 Supervisor 单选一个 Worker 串行执行，本版支持多 Worker **并行执行** + **依赖链串行**，真正发挥 Graph DAG 的编排能力。
> 
> 参考文档：[Spring AI Alibaba Graph 官方文档](https://java2ai.com/en/docs/1.0.0.2/tutorials/graph/whats-spring-ai-alibaba-graph/)

## 一、架构演进对比

### 1.1 三种方案对比

| 维度 | 方案A：手写编排（文档11） | 方案B-旧：Graph串行路由 | 方案B-新：Graph并行协作（本文档） |
|------|--------------------------|------------------------|-------------------------------|
| 编排方式 | 自己写 OrchestratorService | Supervisor 单选一个 Worker | Planner 输出执行计划，多 Worker 并行 |
| 并行能力 | 需自己用 CompletableFuture | 不支持（单选） | 框架原生并行分支 |
| 路由决策 | LLM 输出 JSON 任务计划 | LLM 输出单个 Worker 名称 | LLM 输出结构化执行计划（含并行/依赖） |
| 结果汇总 | 自己写汇总逻辑 | 透传（单Worker不需要汇总） | Synthesizer 用 LLM 智能汇总多 Worker 结果 |
| 典型场景 | "搜文章并分析" → 串行执行 | "搜文章并分析" → 只能选一个 | "搜文章并分析" → search 和 writing 并行，analysis 等 search 完再执行 |

### 1.2 核心概念回顾

Spring AI Alibaba Graph（Java 版 LangGraph）核心概念：

- **StateGraph**：状态图，定义节点和边的容器
- **Node（NodeAction）**：节点，封装具体操作（LLM调用、Tool调用、数据处理）
- **Edge**：边，定义节点之间的转移关系（普通边 / 条件边）
- **OverAllState**：全局状态，所有节点共享的数据容器
- **KeyStrategy**：状态字段的更新策略（ReplaceStrategy 覆盖 / AppendStrategy 追加）
- **并行分支**：从同一节点出发的多条边，框架自动并行执行目标节点

## 二、并行架构设计

### 2.1 Graph 拓扑结构

```
                         ┌─────────────┐
                         │    START    │
                         └──────┬──────┘
                                │
                                ▼
                         ┌─────────────┐
                         │   Planner   │  执行计划节点（LLM分析意图，输出执行计划）
                         │  (LLM规划)  │
                         └──────┬──────┘
                                │ ConditionalEdge（多返回值 → 并行分支）
                 ┌──────────────┼──────────────┬──────────────┐
                 ▼              ▼              ▼              ▼
          ┌──────────┐   ┌──────────┐   ┌─────────┐   ┌────────┐
          │  Search  │   │ Analysis │   │ Writing │   │  Chat  │
          │  Worker  │   │  Worker  │   │ Worker  │   │ Worker │
          │(有Tool)  │   │(有Tool)  │   │(纯LLM)  │   │(纯LLM) │
          └────┬─────┘   └────┬─────┘   └────┬────┘   └───┬────┘
               │              │              │             │
               └──────────────┼──────────────┼─────────────┘
                              ▼
                       ┌─────────────┐
                       │ Synthesizer │  智能汇总节点（多Worker时LLM汇总，单Worker时透传）
                       └──────┬──────┘
                              │
                              ▼
                       ┌─────────────┐
                       │     END     │
                       └─────────────┘
```

### 2.2 并行执行示例

**场景1：简单闲聊 "你好"**
```
START → Planner(输出{"tasks":[{"worker":"chat","task":"回复问候"}]}) → Chat Worker → Synthesizer(透传) → END
```
LLM调用：2次（Planner + Chat）

**场景2：搜索文章 "搜几篇Java并发的文章"**
```
START → Planner(输出{"tasks":[{"worker":"search","task":"搜索Java并发文章"}]}) → Search Worker → Synthesizer(透传) → END
```
LLM调用：2次 + Tool Calling

**场景3：并行搜索 "帮我搜Java并发的文章，顺便查下最新JDK版本"**
```
START → Planner(输出{"tasks":[{"worker":"search","task":"搜索Java并发文章"},{"worker":"chat","task":"查询最新JDK版本"}]})
      → Search Worker ──┐
      → Chat Worker ────┤ 并行执行（各自拿到Planner定制的精简任务描述）
                         ▼
      Synthesizer(LLM汇总两个结果) → END
```
LLM调用：4次（Planner + 2个Worker并行 + Synthesizer汇总）

**场景4：搜索+分析 "搜几篇Spring Boot文章并总结下"**
```
START → Planner(输出{"tasks":[{"worker":"search_then_analysis","task":"搜索Spring Boot文章并总结分析"}]})
      → Search Worker → Analysis Worker(读取search结果+Planner任务描述) → Synthesizer(透传) → END
```
LLM调用：3次（Planner + Search + Analysis），analysis 依赖 search 所以串行

### 2.3 设计要点

1. **Planner 替代 Supervisor**：不再单选，而是输出一个结构化执行计划（哪些Worker要执行、每个Worker的定制任务描述、是否有依赖）
2. **Planner 拿历史，Worker 拿指令**：Planner 注入完整历史消息理解上下文和指代关系，为每个 Worker 生成精简的任务描述。Worker 只读取 Planner 给的任务描述，不读取历史消息，prompt 更聚焦、token 消耗更少
3. **条件边返回多值 → 并行**：Graph 框架中，条件边返回多个目标节点时，自动并行执行
4. **OverAllState + AppendStrategy**：多个并行 Worker 的结果用 AppendStrategy 追加到列表，不会互相覆盖
5. **Synthesizer 智能汇总**：单 Worker 时透传，多 Worker 时用 LLM 汇总

## 三、依赖配置

### 3.1 pom.xml 新增依赖

```xml
<!-- Spring AI Alibaba Graph（Multi-Agent 图编排框架） -->
<dependency>
    <groupId>com.alibaba.cloud.ai</groupId>
    <artifactId>spring-ai-alibaba-graph-core</artifactId>
    <version>1.1.2.0</version>
</dependency>
```

> 版本兼容：`1.1.2.0` 对应 Spring AI 1.1.x，与项目当前版本兼容。

## 四、核心代码

### 4.1 新增文件清单

```
src/main/java/com/easyjob/agent/graph/
├── state/
│   └── AgentStateFactory.java         // 全局状态定义
├── node/
│   ├── PlannerNode.java               // 执行计划节点（替代旧版SupervisorNode）
│   ├── SearchWorkerNode.java          // 搜索Worker
│   ├── AnalysisWorkerNode.java        // 分析Worker
│   ├── WritingWorkerNode.java         // 写作Worker
│   ├── ChatWorkerNode.java            // 聊天Worker
│   └── SynthesizerNode.java           // 智能汇总节点
├── edge/
│   └── PlannerDispatcher.java         // 执行计划条件路由（支持多返回值并行）
└── config/
    └── AgentGraphConfiguration.java   // Graph Bean定义（并行拓扑）
```


### 4.2 AgentStateFactory — 全局状态定义（支持并行写入）

#### 设计讲解

OverAllState 是 Graph 框架的"全局黑板"——所有节点共享的数据容器。每个节点执行完后，把结果写到这个黑板上，下一个节点从黑板上读取数据。

关键问题：**并行 Worker 同时往黑板上写数据，怎么办？**

这就是 `KeyStrategy` 的作用：
- `ReplaceStrategy`（覆盖策略）：后写入的值覆盖先写入的。适合只有一个节点会写的字段，比如 `userMessage`、`finalReply`
- `AppendStrategy`（追加策略）：新值追加到列表末尾，不会覆盖。适合多个并行节点同时写的字段，比如 `workerResults`

举个例子：Search Worker 和 Writing Worker 并行执行，都往 `workerResults` 写结果。如果用 ReplaceStrategy，后完成的会覆盖先完成的，丢失数据。用 AppendStrategy，两个结果都会追加到列表里，Synthesizer 就能拿到所有 Worker 的结果。

```java
package com.easyjob.agent.graph.state;

import com.alibaba.cloud.ai.graph.KeyStrategy;
import com.alibaba.cloud.ai.graph.KeyStrategyFactory;
import com.alibaba.cloud.ai.graph.state.strategy.AppendStrategy;
import com.alibaba.cloud.ai.graph.state.strategy.ReplaceStrategy;

import java.util.HashMap;
import java.util.Map;

/**
 * Agent Graph 全局状态定义（并行版）
 * 
 * 关键设计：
 * - workerResults 使用 AppendStrategy，多个并行Worker的结果追加到同一个列表
 * - articleCards 使用 AppendStrategy，多个Worker产生的文章卡片合并
 * - taskDescriptions 存储 Planner 为每个 Worker 定制的任务描述
 * - historyMessages 只给 Planner 用，Worker 不读取历史消息
 * - 其他字段使用 ReplaceStrategy，后写入的覆盖先写入的
 */
public class AgentStateFactory implements KeyStrategyFactory {

    @Override
    public Map<String, KeyStrategy> apply() {
        Map<String, KeyStrategy> strategies = new HashMap<>();

        // === 输入字段（ReplaceStrategy） ===
        strategies.put("userMessage", new ReplaceStrategy());       // 用户原始消息
        strategies.put("conversationId", new ReplaceStrategy());    // 会话ID
        strategies.put("userId", new ReplaceStrategy());            // 用户ID
        strategies.put("historyMessages", new ReplaceStrategy());   // 历史对话消息列表（仅Planner使用）

        // === Planner 输出字段 ===
        strategies.put("executionPlan", new ReplaceStrategy());     // 执行计划（JSON字符串，LLM原始输出）
        strategies.put("activeWorkers", new ReplaceStrategy());     // 需要执行的Worker名称列表 List<String>
        strategies.put("taskDescriptions", new ReplaceStrategy());  // 【新增】Planner为每个Worker定制的任务描述 Map<String, String>
        strategies.put("degraded", new ReplaceStrategy());          // 【新增】降级标记，Planner解析失败时为true，ChatWorker据此决定是否注入历史消息

        // === Worker 输出字段（AppendStrategy：并行Worker结果追加） ===
        strategies.put("workerResults", new AppendStrategy());      // 所有Worker的结果列表
        strategies.put("articleCards", new AppendStrategy());       // 文章卡片列表（多Worker合并）

        // === 中间传递字段 ===
        strategies.put("searchResult", new ReplaceStrategy());      // search结果（供analysis依赖读取）

        // === 最终输出 ===
        strategies.put("finalReply", new ReplaceStrategy());        // 最终回复文本

        return strategies;
    }
}
```

> **字段设计总结**：
> - 输入字段（`userMessage`、`conversationId`、`userId`）：由 AgentService 在 Graph 启动时写入，全程不变，所以用 Replace
> - `historyMessages`：历史对话消息，**仅 Planner 读取**，用于理解上下文和指代关系。Worker 不读取历史消息
> - Planner 输出（`executionPlan`、`activeWorkers`、`taskDescriptions`、`degraded`）：只有 Planner 一个节点写，用 Replace
> - `taskDescriptions`：**核心新增字段**，`Map<String, String>` 类型，key 是 Worker 名称，value 是 Planner 为该 Worker 定制的精简任务描述。Worker 从这里读取自己的任务指令，而不是读取原始用户消息或历史消息
> - `degraded`：**降级标记**，`Boolean` 类型。Planner 输出解析失败时为 `true`，此时 `taskDescriptions` 中的值是原始用户消息而非定制指令。ChatWorker 检测到 `degraded=true` 会注入历史消息兜底
> - Worker 输出（`workerResults`、`articleCards`）：多个并行 Worker 同时写，**必须用 Append**
> - 中间传递（`searchResult`）：Search Worker 写入，Analysis Worker 读取，只有一个写入者，用 Replace
> - 最终输出（`finalReply`）：Synthesizer 写入，只有一个写入者，用 Replace
>
> **历史消息策略的核心思想**：
> - Planner 是"战略指挥官"，需要看到完整的对话历史来理解上下文（比如用户说"帮我分析下第一篇"，Planner 需要知道之前搜了什么）
> - Worker 是"战术执行者"，只需要 Planner 给的精简任务指令（比如"搜索Java并发相关文章"），不需要看历史消息
> - 这样做的好处：Worker 的 prompt 更精简、上下文更聚焦，LLM 执行效率更高，token 消耗更少

### 4.3 PlannerNode — 执行计划节点

#### 设计讲解

Planner 是整个并行架构的"大脑"。它的职责是：**分析用户说了什么，决定需要哪些 Worker 来处理，并为每个 Worker 定制精简的任务描述**。

与旧版 SupervisorNode 的核心区别：
- 旧版只能输出一个 Worker 名称（如 `"search"`），是单选
- 新版输出一个结构化 JSON 执行计划，包含多个 Worker 及其各自的任务描述

**Planner 输出格式**：
```json
{
  "tasks": [
    {"worker": "search", "task": "搜索Java并发相关的文章"},
    {"worker": "writing", "task": "列一个Java并发文章的写作大纲"}
  ]
}
```

每个 task 对象包含：
- `worker`：Worker 名称（search / analysis / writing / chat）
- `task`：Planner 为该 Worker 定制的精简任务描述

**为什么 Worker 不直接拿用户原始消息？**

考虑这个场景：用户说"帮我搜几篇Java并发的文章，顺便帮我列个写作大纲"。如果 SearchWorker 和 WritingWorker 都拿到完整的原始消息，它们各自都需要理解"这句话里哪部分是给我的"，这增加了 LLM 的理解负担。

更好的做法是 Planner 作为"战略指挥官"，把复合请求拆解成精准的"战术指令"：
- 给 SearchWorker 的指令："搜索Java并发相关的文章"
- 给 WritingWorker 的指令："列一个Java并发文章的写作大纲"

每个 Worker 拿到的是一个清晰、聚焦的任务，不需要自己去理解复杂的复合请求。

**关于历史消息的策略**：

Planner 拿完整历史消息，Worker 不拿历史消息。原因：
- Planner 需要历史来理解指代关系（如"帮我分析下第一篇"→ Planner 知道之前搜了什么，把"第一篇"解析为具体的文章信息写入任务描述）
- Worker 只需要 Planner 给的精简任务指令，不需要看历史。这样 Worker 的 prompt 更短、上下文更聚焦、token 消耗更少、LLM 执行效率更高

**关于 `return Map.of(...)` 如何写入 OverAllState**：

`NodeAction.apply()` 的返回值 `Map<String, Object>` 会被 Graph 框架自动合并到 OverAllState 中。你不需要手动调用 `state.put()` 或 `state.set()`，框架会根据 `AgentStateFactory` 中定义的 `KeyStrategy` 来决定合并方式（Replace 覆盖 / Append 追加）。所以 `return Map.of("activeWorkers", activeWorkers, "taskDescriptions", taskDescriptions)` 就等于把这两个字段写入了全局状态，下一个节点（DispatcherNode）通过 `state.value("activeWorkers")` 和 `state.value("taskDescriptions")` 就能读到。

这是 LangGraph 的核心设计——**节点是无副作用的纯函数**（输入 state → 输出要更新的字段），框架负责状态合并和流转。

另外，LLM 的输出不一定总是规范的 JSON，所以 `parsePlan` 方法有三级保障：
1. 直接解析结构化 JSON（`{"tasks": [...]}` 格式）
2. 尝试解析简单 JSON 数组（`["search", "chat"]` 格式，兼容 LLM 偶尔输出简化格式）
3. 从文本中提取已知 Worker 名称（最终兜底）

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 执行计划节点（替代旧版 SupervisorNode）
 * 
 * 核心职责：
 * 1. 注入完整历史消息，理解对话上下文和指代关系
 * 2. 分析用户意图，决定需要哪些 Worker 协作
 * 3. 为每个 Worker 定制精简的任务描述（"战术指令"）
 * 4. 输出结构化执行计划 JSON
 * 
 * 输出格式：
 * {"tasks": [{"worker": "search", "task": "搜索Java并发文章"}, {"worker": "writing", "task": "列写作大纲"}]}
 * 
 * 依赖链约定：worker 名称包含 "_then_" 表示串行依赖（如 "search_then_analysis"）
 */
@Slf4j
public class PlannerNode implements NodeAction {

    private final ChatClient chatClient;

    private static final String PLANNER_PROMPT = """
            你是一个任务规划器，负责分析用户请求，决定需要哪些专家协作，并为每个专家编写精准的任务指令。
            
            【可用的专家】
            - search: 信息检索专家。搜索平台文章（关键词/语义搜索）和联网搜索实时信息
            - analysis: 内容分析专家。阅读文章详情并深度分析、对比、总结（必须先有search结果）
            - writing: 写作助手。生成文章大纲、润色内容、提供写作建议
            - chat: 日常对话和技术问答专家。闲聊、技术问题、概念解释
            
            【输出规则】
            严格输出一个JSON对象，不要输出其他任何内容。格式如下：
            {"tasks": [{"worker": "专家名称", "task": "为该专家定制的具体任务描述"}]}
            
            【任务描述编写要求】
            - 每个专家的 task 必须是精简、聚焦的指令，只包含该专家需要完成的部分
            - 如果用户消息中有指代（如"第一篇"、"上面那个"），你必须根据对话历史解析出具体内容，写入 task
            - task 描述要足够清晰，让专家不需要看对话历史就能理解并执行
            
            【路由规则】
            1. 简单问候、闲聊、技术问答 → chat
            2. 搜索文章、查找信息 → search
            3. 搜索并分析文章 → search_then_analysis（analysis依赖search，必须串行）
            4. 写作帮助 → writing
            5. 搜索信息 + 写作帮助 → search + writing（无依赖，可并行）
            6. 搜索信息 + 技术问答 → search + chat（无依赖，可并行）
            
            【特殊标记】
            - worker 名称为 "search_then_analysis" 表示 search → analysis 的依赖链
            - 依赖链只需要一个 task 对象，task 描述写给最终的 analysis 专家
            - search 专家会自动根据 analysis 的任务描述来搜索相关内容
            
            【示例】
            用户："帮我搜几篇Java并发的文章"
            → {"tasks": [{"worker": "search", "task": "搜索Java并发相关的文章"}]}
            
            用户："你好"
            → {"tasks": [{"worker": "chat", "task": "回复用户的问候"}]}
            
            用户："帮我搜Java文章并总结下"
            → {"tasks": [{"worker": "search_then_analysis", "task": "搜索Java相关文章，然后对搜索结果进行总结分析"}]}
            
            用户："帮我搜下最新新闻，顺便帮我列个文章大纲"
            → {"tasks": [{"worker": "search", "task": "搜索最新新闻资讯"}, {"worker": "writing", "task": "列一个新闻类文章的写作大纲"}]}
            
            用户："Spring Boot是什么，帮我搜几篇相关文章"
            → {"tasks": [{"worker": "search", "task": "搜索Spring Boot相关的文章"}, {"worker": "chat", "task": "解释Spring Boot是什么，包括核心概念和特点"}]}
            
            用户消息：%s
            """;

    public PlannerNode(ChatModel chatModel) {
        this.chatClient = ChatClient.builder(chatModel).build();
    }

    @Override
    public Map<String, Object> apply(OverAllState state) throws Exception {
        String userMessage = state.value("userMessage", "");
        @SuppressWarnings("unchecked")
        List<Map<String, String>> history = state.value("historyMessages", List.of());

        // 构建带历史上下文的消息列表，让Planner能理解指代（如"帮我分析下第一篇"）
        // 只有 Planner 注入历史消息，Worker 不注入
        List<Message> messages = new ArrayList<>();
        for (Map<String, String> msg : history) {
            if ("user".equals(msg.get("role"))) {
                messages.add(new UserMessage(msg.get("content")));
            } else if ("assistant".equals(msg.get("role"))) {
                messages.add(new AssistantMessage(msg.get("content")));
            }
        }
        messages.add(new UserMessage(PLANNER_PROMPT.formatted(userMessage)));

        String result = chatClient.prompt()
                .messages(messages)
                .call()
                .content();

        // 解析执行计划，提取 activeWorkers 列表和 taskDescriptions 映射
        PlanResult planResult = parsePlan(result, userMessage);
        
        log.info("Planner执行计划: userMessage='{}', activeWorkers={}, taskDescriptions={}, degraded={}", 
                truncate(userMessage, 50), planResult.activeWorkers, planResult.taskDescriptions, planResult.degraded);

        Map<String, Object> output = new HashMap<>();
        output.put("executionPlan", result);
        output.put("activeWorkers", planResult.activeWorkers);
        output.put("taskDescriptions", planResult.taskDescriptions);
        output.put("degraded", planResult.degraded);
        return output;
    }

    /**
     * 解析结果的内部数据类
     * degraded: 是否降级（Planner输出解析失败，task描述为原始用户消息而非定制指令）
     */
    private record PlanResult(List<String> activeWorkers, Map<String, String> taskDescriptions, boolean degraded) {}

    /**
     * 解析LLM输出的执行计划
     * 三级保障：解析结构化JSON → 解析简单数组 → 文本提取降级
     */
    private PlanResult parsePlan(String result, String userMessage) {
        if (result == null || result.isBlank()) {
            return new PlanResult(List.of("chat"), Map.of("chat", userMessage), true);
        }

        String json = result.trim();
        // 去掉可能的 ```json ``` 包裹
        if (json.contains("```")) {
            json = json.replaceAll("```json\\s*", "").replaceAll("```\\s*", "").trim();
        }

        // 第一级：解析结构化JSON {"tasks": [{"worker": "...", "task": "..."}]}
        try {
            JSONObject obj = JSON.parseObject(json);
            JSONArray tasks = obj.getJSONArray("tasks");
            if (tasks != null && !tasks.isEmpty()) {
                List<String> workers = new ArrayList<>();
                Map<String, String> descriptions = new HashMap<>();
                for (int i = 0; i < tasks.size(); i++) {
                    JSONObject taskObj = tasks.getJSONObject(i);
                    String worker = taskObj.getString("worker").trim().toLowerCase();
                    String task = taskObj.getString("task");
                    if (isValidWorker(worker)) {
                        workers.add(worker);
                        // 依赖链的 task 描述同时给 search 和 analysis
                        if (worker.contains("_then_")) {
                            String[] parts = worker.split("_then_");
                            descriptions.put(parts[0], task);  // search 也能读到任务描述
                            if (parts.length > 1) {
                                descriptions.put(parts[1], task);  // analysis 读到任务描述
                            }
                        } else {
                            descriptions.put(worker, task);
                        }
                    }
                }
                if (!workers.isEmpty()) {
                    return new PlanResult(workers, descriptions, false);  // 正常解析，不降级
                }
            }
        } catch (Exception ignored) {}

        // 第二级：尝试解析简单JSON数组 ["search", "chat"]（兼容LLM偶尔输出简化格式）
        try {
            JSONArray array = JSON.parseArray(json);
            List<String> workers = new ArrayList<>();
            Map<String, String> descriptions = new HashMap<>();
            for (int i = 0; i < array.size(); i++) {
                String worker = array.getString(i).trim().toLowerCase();
                if (isValidWorker(worker)) {
                    workers.add(worker);
                    descriptions.put(worker, userMessage);  // 没有定制描述，降级用原始消息
                }
            }
            if (!workers.isEmpty()) {
                log.warn("Planner输出为简单数组格式（缺少task描述），降级使用原始消息作为任务描述");
                return new PlanResult(workers, descriptions, true);  // 降级
            }
        } catch (Exception ignored) {}

        // 第三级：从文本中提取已知Worker名称（最终兜底）
        String lower = result.toLowerCase();
        List<String> extracted = new ArrayList<>();
        Map<String, String> descriptions = new HashMap<>();
        if (lower.contains("search_then_analysis")) {
            extracted.add("search_then_analysis");
            descriptions.put("search", userMessage);
            descriptions.put("analysis", userMessage);
        } else {
            if (lower.contains("search")) {
                extracted.add("search");
                descriptions.put("search", userMessage);
            }
            if (lower.contains("analysis")) {
                extracted.add("analysis");
                descriptions.put("analysis", userMessage);
            }
        }
        if (lower.contains("writing")) {
            extracted.add("writing");
            descriptions.put("writing", userMessage);
        }
        if (lower.contains("chat")) {
            extracted.add("chat");
            descriptions.put("chat", userMessage);
        }
        if (!extracted.isEmpty()) {
            log.warn("Planner输出解析失败，从文本提取Worker名称，降级使用原始消息作为任务描述");
            return new PlanResult(extracted, descriptions, true);  // 降级
        }

        // 最终降级
        log.warn("Planner输出完全解析失败，降级为chat, 原始输出: {}", result);
        return new PlanResult(List.of("chat"), Map.of("chat", userMessage), true);  // 降级
    }

    private boolean isValidWorker(String name) {
        return "search".equals(name) || "analysis".equals(name) 
                || "writing".equals(name) || "chat".equals(name)
                || "search_then_analysis".equals(name);
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}
```

> **Planner 核心设计要点**：
> 
> 1. **结构化输出**：从简单数组 `["search"]` 升级为 `{"tasks": [{"worker": "search", "task": "..."}]}`，每个 Worker 都有定制的任务描述
> 
> 2. **任务描述的价值**：Planner 作为"战略指挥官"，把用户的复合请求拆解为多个精准的"战术指令"。Worker 拿到的不是模糊的原始消息，而是 Planner 理解上下文后提炼出的清晰任务
> 
> 3. **指代解析**：用户说"帮我分析下第一篇"，Planner 看到历史消息知道之前搜了什么，会把 task 写成"分析《xxx》这篇文章的核心观点"，Worker 不需要看历史就能执行
> 
> 4. **历史消息只给 Planner**：Worker 不注入历史消息，prompt 更精简，token 消耗更少，LLM 执行效率更高
> 
> 5. **三级解析保障 + 降级标记**：结构化 JSON → 简单数组（兼容） → 文本提取（兜底），确保即使 LLM 输出不规范，系统也不会崩溃。降级时用原始用户消息作为任务描述，并设置 `degraded=true`，ChatWorker 检测到降级标记会注入历史消息兜底，避免因缺少上下文导致回复质量下降
> 
> 6. **依赖链的 task 描述**：`search_then_analysis` 的 task 描述会同时写入 `search` 和 `analysis` 两个 key，这样两个 Worker 都能读到任务描述

### 4.4 Worker 节点

#### 设计讲解

Worker 是真正干活的节点。每个 Worker 有独立的 system prompt 和 Tool 配置，互不干扰。这就是 Multi-Agent 的核心优势——**上下文隔离**。

单 Agent 架构下，所有能力（搜索、分析、写作、闲聊）混在一个 system prompt 里，模型需要同时理解所有 Tool 的用法，prompt 臃肿且容易混乱。Multi-Agent 架构下，每个 Worker 只关注自己的职责，prompt 精简，效果更好。

**Worker 的输入来源**：

Worker 不再读取用户原始消息（`userMessage`）或历史消息（`historyMessages`），而是从 `taskDescriptions` 中读取 Planner 为自己定制的任务描述。这是新方案的核心改动：

```
旧方案：Worker 读取 userMessage + historyMessages → prompt 臃肿，Worker 需要自己理解复合请求
新方案：Worker 读取 taskDescriptions.get("自己的名字") → prompt 精简，任务清晰聚焦
```

举个例子，用户说"帮我搜几篇Java并发的文章，顺便帮我列个写作大纲"：
- SearchWorker 收到的任务：`"搜索Java并发相关的文章"`（不是完整的原始消息）
- WritingWorker 收到的任务：`"列一个Java并发文章的写作大纲"`（不是完整的原始消息）

每个 Worker 拿到的是一个清晰、聚焦的指令，不需要自己去理解复杂的复合请求，也不需要看历史消息。

Worker 节点的输出格式统一为 `Map{workerName, result}`，写入 `workerResults` 字段（AppendStrategy）。这样 Synthesizer 就能统一处理所有 Worker 的结果，不管有几个 Worker、是什么类型。

SearchWorker 比较特殊，它额外写入了 `searchResult` 字段。这是为了支持依赖链——AnalysisWorker 需要读取 SearchWorker 的搜索结果作为输入。

#### 4.4.1 SearchWorkerNode

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.DocumentChunk;
import com.easyjob.vo.ArticleCardVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 搜索Worker节点
 * 
 * 职责：搜索平台文章 + 联网搜索实时信息
 * 拥有Tool：ArticleTool, BochaSearchTool
 * 内置RAG：自动检索向量库注入system prompt
 * 
 * 输入：从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
 * 输出：
 * - workerResults: {workerName: "search", result: "..."}（追加到列表）
 * - searchResult: 搜索结果文本（供AnalysisWorker依赖读取）
 * - articleCards: 文章卡片列表（追加）
 */
@Slf4j
public class SearchWorkerNode implements NodeAction {

    private final ChatModel chatModel;
    private final ArticleTool articleTool;
    private final BochaSearchTool bochaSearchTool;
    private final EsVectorStore esVectorStore;
    private final RedisComponent redisComponent;

    private static final String SEARCH_SYSTEM_PROMPT = """
            你是一个信息检索助手，专门负责搜索和检索信息。
            
            【职责】
            - 根据任务指令，使用工具搜索平台文章或联网搜索实时信息
            - 返回结构化的搜索结果，包含标题、摘要、关键信息
            - 不要对搜索结果做过多分析，只负责检索和整理
            
            【当前日期】%s
            
            【输出要求】
            - 直接返回搜索结果，不要添加多余的开场白
            - 保持结果简洁、结构化
            - 不要把文章id露出来
            """;

    public SearchWorkerNode(ChatModel chatModel, ArticleTool articleTool,
                            BochaSearchTool bochaSearchTool, EsVectorStore esVectorStore,
                            RedisComponent redisComponent) {
        this.chatModel = chatModel;
        this.articleTool = articleTool;
        this.bochaSearchTool = bochaSearchTool;
        this.esVectorStore = esVectorStore;
        this.redisComponent = redisComponent;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        Long conversationId = state.value("conversationId", 0L);
        String today = java.time.LocalDate.now().toString();

        // 从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("search", state.value("userMessage", ""));

        // RAG检索（用任务描述作为检索query，比原始消息更精准）
        String ragContext = retrieveRagContext(taskInput);
        String systemPrompt = SEARCH_SYSTEM_PROMPT.formatted(today);
        if (!ragContext.isEmpty()) {
            systemPrompt += "\n\n【RAG参考资料】\n" + ragContext;
        }

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(systemPrompt)
                .build();

        // 直接用 Planner 的任务描述作为 user message，不注入历史消息
        String result = workerClient.prompt()
                .user(taskInput)
                .tools(articleTool, bochaSearchTool)
                .toolContext(Map.of("conversationId", conversationId))
                .call()
                .content();

        // 获取文章卡片
        List<ArticleCardVO> cards = redisComponent.getAndClearArticleCards(conversationId);

        log.info("SearchWorker执行完成, 任务: '{}', 结果长度: {}, 文章卡片数: {}", 
                truncate(taskInput, 50), result.length(), cards.size());

        // 构建Worker结果（追加到workerResults列表）
        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "search");
        workerResult.put("result", result);

        Map<String, Object> output = new HashMap<>();
        output.put("workerResults", workerResult);      // AppendStrategy → 追加到列表
        output.put("searchResult", result);              // ReplaceStrategy → 供analysis读取
        if (!cards.isEmpty()) {
            output.put("articleCards", cards);            // AppendStrategy → 追加卡片
        }
        return output;
    }

    private String retrieveRagContext(String query) {
        try {
            List<DocumentChunk> chunks = esVectorStore.search(query, 5, 0.7f);
            if (chunks.isEmpty()) return "";

            StringBuilder context = new StringBuilder();
            for (int i = 0; i < chunks.size(); i++) {
                DocumentChunk chunk = chunks.get(i);
                if (chunk.getContent() == null || chunk.getContent().isBlank()) continue;
                context.append(String.format("【参考%d】来自《%s》:\n%s\n\n",
                        i + 1, chunk.getTitle(), chunk.getContent()));
            }
            return context.toString();
        } catch (Exception e) {
            log.error("SearchWorker RAG检索失败", e);
            return "";
        }
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}
```

#### 4.4.2 AnalysisWorkerNode

> AnalysisWorker 的关键在于它会从 OverAllState 中读取 `searchResult` 字段。在依赖链场景（`search_then_analysis`）中，SearchWorker 先执行并把搜索结果写入 `searchResult`，然后 AnalysisWorker 读取这个结果作为分析的输入。同时，AnalysisWorker 从 `taskDescriptions` 读取 Planner 定制的任务描述，而不是读取原始用户消息或历史消息。

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.tool.ArticleTool;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;

import java.util.HashMap;
import java.util.Map;

/**
 * 分析Worker节点
 * 
 * 职责：阅读文章详情，进行深度分析、对比、总结
 * 依赖：读取 searchResult 字段（由 SearchWorker 写入）
 * 输入：从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
 * 拥有Tool：ArticleTool（getArticleDetail）
 */
@Slf4j
public class AnalysisWorkerNode implements NodeAction {

    private final ChatModel chatModel;
    private final ArticleTool articleTool;

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

    public AnalysisWorkerNode(ChatModel chatModel, ArticleTool articleTool) {
        this.chatModel = chatModel;
        this.articleTool = articleTool;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        Long conversationId = state.value("conversationId", 0L);

        // 从 taskDescriptions 读取 Planner 定制的任务描述
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("analysis", state.value("userMessage", ""));

        // 读取前置搜索结果（由SearchWorker写入）
        String searchResult = state.value("searchResult", "");
        
        // 组合输入：前置搜索结果 + Planner的任务描述
        String input;
        if (!searchResult.isEmpty()) {
            input = "【前置搜索结果】\n" + searchResult + "\n\n【分析任务】" + taskInput;
        } else {
            input = taskInput;
        }

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(ANALYSIS_SYSTEM_PROMPT)
                .build();

        String result = workerClient.prompt()
                .user(input)
                .tools(articleTool)
                .toolContext(Map.of("conversationId", conversationId))
                .call()
                .content();

        log.info("AnalysisWorker执行完成, 任务: '{}', 结果长度: {}", 
                truncate(taskInput, 50), result.length());

        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "analysis");
        workerResult.put("result", result);

        return Map.of("workerResults", workerResult);
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}
```

#### 4.4.3 WritingWorkerNode

> WritingWorker 和 ChatWorker 都是纯 LLM 节点，不需要 Tool。它们从 `taskDescriptions` 读取 Planner 定制的任务描述，不注入历史消息。纯 LLM Worker 的优势是执行速度快（不需要等 Tool Calling），适合作为并行分支中的"轻量级"Worker。

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;

import java.util.HashMap;
import java.util.Map;

/**
 * 写作Worker节点（纯LLM，无Tool）
 * 
 * 输入：从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
 */
@Slf4j
public class WritingWorkerNode implements NodeAction {

    private final ChatModel chatModel;

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

    public WritingWorkerNode(ChatModel chatModel) {
        this.chatModel = chatModel;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        // 从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("writing", state.value("userMessage", ""));

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(WRITING_SYSTEM_PROMPT)
                .build();

        // 直接用 Planner 的任务描述作为 user message
        String result = workerClient.prompt()
                .user(taskInput)
                .call()
                .content();

        log.info("WritingWorker执行完成, 任务: '{}', 结果长度: {}", 
                truncate(taskInput, 50), result.length());

        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "writing");
        workerResult.put("result", result);

        return Map.of("workerResults", workerResult);
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}
```

#### 4.4.4 ChatWorkerNode

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

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 聊天Worker节点（纯LLM，无Tool）
 * 
 * 输入：从 taskDescriptions 读取 Planner 定制的任务描述（不读取历史消息）
 * 
 * 降级兜底：当 Planner 输出解析失败（degraded=true）时，ChatWorker 的 task 描述
 * 是用户原始消息（可能包含指代，如"刚才那个怎么做"）。此时 ChatWorker 需要注入
 * 历史消息才能理解上下文，否则回复质量会很差。
 * 
 * 正常流程下，Planner 已经把指代解析后的清晰指令写入 task 描述，
 * ChatWorker 不需要历史消息就能准确回答。
 */
@Slf4j
public class ChatWorkerNode implements NodeAction {

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

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        String today = java.time.LocalDate.now().toString();
        boolean degraded = state.value("degraded", false);

        // 从 taskDescriptions 读取 Planner 定制的任务描述
        Map<String, String> taskDescriptions = state.value("taskDescriptions", Map.of());
        String taskInput = taskDescriptions.getOrDefault("chat", state.value("userMessage", ""));

        ChatClient workerClient = ChatClient.builder(chatModel)
                .defaultSystem(CHAT_SYSTEM_PROMPT.formatted(today))
                .build();

        String result;
        if (degraded) {
            // 降级模式：Planner解析失败，task描述是原始用户消息（可能含指代）
            // 需要注入历史消息让LLM理解上下文
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

            result = workerClient.prompt()
                    .messages(messages)
                    .call()
                    .content();
            log.info("ChatWorker（降级模式）执行完成, 注入历史消息{}条, 结果长度: {}", 
                    history.size(), result.length());
        } else {
            // 正常模式：Planner已解析好清晰的任务描述，不需要历史消息
            result = workerClient.prompt()
                    .user(taskInput)
                    .call()
                    .content();
            log.info("ChatWorker执行完成, 任务: '{}', 结果长度: {}", 
                    truncate(taskInput, 50), result.length());
        }

        Map<String, Object> workerResult = new HashMap<>();
        workerResult.put("workerName", "chat");
        workerResult.put("result", result);

        return Map.of("workerResults", workerResult);
    }

    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }
}
```


### 4.5 SynthesizerNode — 智能汇总节点

#### 设计讲解

Synthesizer 是整个流程的"收口"节点，负责把所有 Worker 的结果整合成一个最终回复。

它有两种工作模式：
- **透传模式**（单 Worker）：只有一个 Worker 执行了，结果直接透传给用户，不浪费一次 LLM 调用。比如用户说"你好"，只有 ChatWorker 执行，Synthesizer 直接把 ChatWorker 的回复返回
- **汇总模式**（多 Worker）：多个 Worker 并行执行完毕，Synthesizer 调用 LLM 把多个结果整合成一个连贯的回复。比如 SearchWorker 返回了搜索结果，WritingWorker 返回了大纲，Synthesizer 把两者融合成一个自然的回答

为什么不直接拼接多个 Worker 的结果？因为简单拼接会导致回复割裂——用户会明显感觉到"这是两个不同的回答拼在一起的"。用 LLM 汇总可以重新组织语言，去除重复内容，让回复像是一个人在回答。

`workerResults` 是一个 `List<Map<String, String>>`，每个元素包含 `workerName`（哪个 Worker 产出的）和 `result`（具体内容）。Synthesizer 遍历这个列表，把所有结果拼成 prompt 交给 LLM 汇总。

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;

import java.util.List;
import java.util.Map;

/**
 * 智能汇总节点
 * 
 * 策略：
 * - 单Worker结果：直接透传，不浪费LLM调用
 * - 多Worker结果：用LLM将多个结果整合为一个连贯的回复
 */
@Slf4j
public class SynthesizerNode implements NodeAction {

    private final ChatModel chatModel;

    private static final String SYNTHESIZE_PROMPT = """
            你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。
            
            【要求】
            - 不要简单拼接，要有逻辑地组织内容
            - 保留关键信息，去除重复内容
            - 使用清晰的结构（标题、列表等）
            - 语言自然流畅，像是一个人在回答
            - 不要提及"专家"、"Worker"、"任务"等内部概念
            
            【用户原始问题】
            %s
            
            【各专家的工作结果】
            %s
            """;

    public SynthesizerNode(ChatModel chatModel) {
        this.chatModel = chatModel;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        String userMessage = state.value("userMessage", "");
        List<Map<String, String>> workerResults = state.value("workerResults", List.of());

        // 单Worker结果：直接透传，不调LLM
        if (workerResults.size() <= 1) {
            String result = workerResults.isEmpty() ? "抱歉，处理出错了" 
                    : workerResults.get(0).get("result");
            log.info("Synthesizer透传单Worker结果, 长度: {}", result.length());
            return Map.of("finalReply", result);
        }

        // 多Worker结果：LLM汇总
        StringBuilder resultsText = new StringBuilder();
        for (Map<String, String> wr : workerResults) {
            resultsText.append(String.format("\n--- %s 的结果 ---\n%s\n", 
                    wr.get("workerName"), wr.get("result")));
        }

        ChatClient synthesizer = ChatClient.builder(chatModel).build();
        String finalReply = synthesizer.prompt()
                .user(SYNTHESIZE_PROMPT.formatted(userMessage, resultsText.toString()))
                .call()
                .content();

        log.info("Synthesizer汇总{}个Worker结果, 最终长度: {}", workerResults.size(), finalReply.length());
        return Map.of("finalReply", finalReply);
    }
}
```

### 4.6 DispatcherNode — 并行调度节点（核心）

#### 设计讲解

DispatcherNode 是整个并行架构中最复杂也最关键的组件。它的职责是：**根据 Planner 输出的执行计划，动态决定哪些 Worker 并行执行、哪些串行执行**。

#### 为什么需要 DispatcherNode？

Graph 框架的 `EdgeAction`（条件边）只能返回一个 String，代表下一个要跳转的节点名称。它无法返回多个节点名称来触发并行。虽然可以在编译期通过 `addConditionalEdges` 定义多条边来实现静态并行，但我们的并行组合是**运行时动态决定**的（由 Planner LLM 输出），编译期无法穷举所有可能的组合（search+writing、search+chat、search_then_analysis+writing...组合爆炸）。

所以我们把并行逻辑封装在一个节点内部，用 Java 的 `CompletableFuture` 实现运行时动态并行。Graph 层面看到的是一条简洁的链（planner → dispatcher → synthesizer），但 dispatcher 内部实际上在并行执行多个 Worker。

#### 核心执行逻辑

DispatcherNode 拿到 `activeWorkers` 列表后，分两类处理：

1. **独立 Worker**（如 `"search"`、`"writing"`）：直接用 `CompletableFuture.runAsync()` 并行执行
2. **依赖链**（如 `"search_then_analysis"`）：按 `_then_` 分割，先执行 search，等 search 完成后再执行 analysis

这两类任务之间也是并行的。比如 `["search_then_analysis", "writing"]`，依赖链和 writing 是并行执行的：
- 线程1：search → analysis（串行）
- 线程2：writing（独立）
- 总耗时 = max(search + analysis, writing)

#### 关于 taskDescriptions 的传递

DispatcherNode 不需要显式传递 `taskDescriptions` 给 Worker。因为 Planner 已经把 `taskDescriptions` 写入了 OverAllState，而 Worker 的 `apply(OverAllState state)` 方法接收的就是同一个 state 对象，所以 Worker 可以直接通过 `state.value("taskDescriptions")` 读取到 Planner 写入的任务描述。

这就是 OverAllState "全局黑板"模式的优势——节点之间的数据传递不需要手动搬运，写入 state 就等于对所有后续节点可见。

#### 线程安全

多个 Worker 并行执行，结果需要写入同一个列表。这里用 `CopyOnWriteArrayList` 保证线程安全。虽然 CopyOnWriteArrayList 写入性能不高（每次写入都复制数组），但 Worker 数量很少（最多4-5个），写入次数极少，完全不是瓶颈。

#### Worker 工厂方法

`createWorker()` 方法根据 Worker 名称创建对应的 NodeAction 实例。每次调用都创建新实例，保证 Worker 之间完全隔离，没有共享状态。

```java
package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.RedisComponent;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ChatModel;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 并行调度节点
 * 
 * 核心设计：
 * 1. 读取 Planner 输出的 activeWorkers 列表
 * 2. 无依赖的 Worker 用 CompletableFuture 并行执行
 * 3. 有依赖的 Worker（如 search_then_analysis）串行执行
 * 4. 所有结果写入 workerResults（AppendStrategy）
 * 
 * 为什么不用 Graph 原生并行分支？
 * Graph 的 EdgeAction 只能返回单个目标节点名称。虽然可以通过构建多条边实现并行，
 * 但那样需要在编译期就确定所有可能的并行组合，不够灵活。
 * 用 DispatcherNode 在运行时动态决定并行策略，更适合 LLM 输出不确定的场景。
 */
@Slf4j
public class DispatcherNode implements NodeAction {

    private final ChatModel chatModel;
    private final ArticleTool articleTool;
    private final BochaSearchTool bochaSearchTool;
    private final EsVectorStore esVectorStore;
    private final RedisComponent redisComponent;

    public DispatcherNode(ChatModel chatModel, ArticleTool articleTool,
                          BochaSearchTool bochaSearchTool, EsVectorStore esVectorStore,
                          RedisComponent redisComponent) {
        this.chatModel = chatModel;
        this.articleTool = articleTool;
        this.bochaSearchTool = bochaSearchTool;
        this.esVectorStore = esVectorStore;
        this.redisComponent = redisComponent;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Object> apply(OverAllState state) throws Exception {
        List<String> activeWorkers = state.value("activeWorkers", List.of("chat"));
        String userMessage = state.value("userMessage", "");
        Long conversationId = state.value("conversationId", 0L);

        log.info("Dispatcher开始调度, activeWorkers: {}", activeWorkers);

        // 分离：依赖链任务 vs 独立并行任务
        List<String> parallelWorkers = new ArrayList<>();
        List<String> chainWorkers = new ArrayList<>();  // search_then_analysis 这种

        for (String worker : activeWorkers) {
            if (worker.contains("_then_")) {
                chainWorkers.add(worker);
            } else {
                parallelWorkers.add(worker);
            }
        }

        // 收集所有结果（线程安全）
        CopyOnWriteArrayList<Map<String, String>> allResults = new CopyOnWriteArrayList<>();
        CopyOnWriteArrayList<Object> allCards = new CopyOnWriteArrayList<>();
        // 用于传递 searchResult 给 analysis
        Map<String, String> sharedContext = new HashMap<>();

        // === 第一阶段：并行执行独立Worker + 依赖链的第一步 ===
        List<CompletableFuture<Void>> futures = new ArrayList<>();

        // 独立Worker并行执行
        for (String workerName : parallelWorkers) {
            futures.add(CompletableFuture.runAsync(() -> {
                try {
                    NodeAction worker = createWorker(workerName);
                    Map<String, Object> result = worker.apply(state);
                    collectResults(result, allResults, allCards);
                } catch (Exception e) {
                    log.error("Worker[{}]执行失败", workerName, e);
                    Map<String, String> errorResult = new HashMap<>();
                    errorResult.put("workerName", workerName);
                    errorResult.put("result", "该模块执行出错，请稍后重试");
                    allResults.add(errorResult);
                }
            }));
        }

        // 依赖链：先执行第一个，再执行第二个
        for (String chain : chainWorkers) {
            futures.add(CompletableFuture.runAsync(() -> {
                try {
                    String[] parts = chain.split("_then_");
                    // 执行第一个Worker（如search）
                    NodeAction firstWorker = createWorker(parts[0]);
                    Map<String, Object> firstResult = firstWorker.apply(state);
                    collectResults(firstResult, allResults, allCards);

                    // 将第一个Worker的结果写入共享上下文
                    if (firstResult.containsKey("searchResult")) {
                        sharedContext.put("searchResult", (String) firstResult.get("searchResult"));
                    }

                    // 执行第二个Worker（如analysis），注入前置结果
                    if (parts.length > 1) {
                        // 创建一个带有searchResult的临时state
                        // AnalysisWorker会从state中读取searchResult
                        NodeAction secondWorker = createWorker(parts[1]);
                        // 这里需要一个能注入searchResult的机制
                        // 由于OverAllState是共享的，第一个Worker已经写入了searchResult
                        Map<String, Object> secondResult = secondWorker.apply(state);
                        collectResults(secondResult, allResults, allCards);
                    }
                } catch (Exception e) {
                    log.error("依赖链[{}]执行失败", chain, e);
                }
            }));
        }

        // 等待所有任务完成
        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        log.info("Dispatcher调度完成, 总结果数: {}, 总卡片数: {}", allResults.size(), allCards.size());

        // 构建输出
        Map<String, Object> output = new HashMap<>();
        output.put("workerResults", new ArrayList<>(allResults));
        if (!allCards.isEmpty()) {
            output.put("articleCards", new ArrayList<>(allCards));
        }
        if (sharedContext.containsKey("searchResult")) {
            output.put("searchResult", sharedContext.get("searchResult"));
        }
        return output;
    }

    /**
     * 根据Worker名称创建对应的NodeAction实例
     */
    private NodeAction createWorker(String workerName) {
        return switch (workerName) {
            case "search" -> new SearchWorkerNode(chatModel, articleTool, bochaSearchTool, esVectorStore, redisComponent);
            case "analysis" -> new AnalysisWorkerNode(chatModel, articleTool);
            case "writing" -> new WritingWorkerNode(chatModel);
            case "chat" -> new ChatWorkerNode(chatModel);
            default -> throw new IllegalArgumentException("未知的Worker: " + workerName);
        };
    }

    /**
     * 收集Worker结果到线程安全列表
     */
    @SuppressWarnings("unchecked")
    private void collectResults(Map<String, Object> result, 
                                CopyOnWriteArrayList<Map<String, String>> allResults,
                                CopyOnWriteArrayList<Object> allCards) {
        Object wr = result.get("workerResults");
        if (wr instanceof Map) {
            allResults.add((Map<String, String>) wr);
        }
        Object cards = result.get("articleCards");
        if (cards instanceof List) {
            allCards.addAll((List<?>) cards);
        }
    }
}
```

> **DispatcherNode 关键代码解读**：
> 1. `activeWorkers` 分流：遍历 Planner 输出的 Worker 列表，包含 `_then_` 的归入依赖链，其余归入并行队列
> 2. `CompletableFuture.runAsync()`：每个独立 Worker 和每条依赖链各启动一个异步线程
> 3. 依赖链内部串行：`parts[0]` 执行完后，结果写入 `sharedContext`，然后 `parts[1]` 从 state 中读取 `searchResult`
> 4. `CompletableFuture.allOf().join()`：等待所有并行任务完成
> 5. 结果收集：所有 Worker 的结果统一收集到 `allResults` 和 `allCards`，写入 OverAllState

### 4.7 AgentGraphConfiguration — 并行版 Graph 配置

#### 设计讲解

这是整个 Graph 的组装入口。对比旧版的配置，变化非常大：

**旧版拓扑**（7个节点 + 条件边）：
```
START → supervisor → (search|analysis|writing|chat) → synthesizer → END
```
需要注册6个节点（supervisor + 4个Worker + synthesizer），定义条件边和4条Worker→synthesizer的边。

**新版拓扑**（3个节点 + 3条边）：
```
START → planner → dispatcher → synthesizer → END
```
只需要注册3个节点，定义3条普通边。极其简洁。

并行逻辑全部封装在 DispatcherNode 内部，Graph 层面完全感知不到。这样做的好处：
- 拓扑图清晰，一眼就能看懂
- 新增 Worker 不需要改 Graph 配置，只需要改 DispatcherNode 的 `createWorker()` 方法
- 调试方便，Graph 的执行日志只有三步

`node_async()` 包装器将 NodeAction 转为异步执行，这是 Graph 框架的要求——所有节点都以异步方式注册，框架内部管理线程调度。

```java
package com.easyjob.agent.graph.config;

import com.alibaba.cloud.ai.graph.StateGraph;
import com.alibaba.cloud.ai.graph.exception.GraphStateException;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.agent.graph.node.*;
import com.easyjob.agent.graph.state.AgentStateFactory;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.component.RedisComponent;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import static com.alibaba.cloud.ai.graph.StateGraph.END;
import static com.alibaba.cloud.ai.graph.StateGraph.START;
import static com.alibaba.cloud.ai.graph.action.AsyncNodeAction.node_async;

/**
 * Agent Graph 配置（并行版）
 * 
 * 拓扑：START → planner → dispatcher → synthesizer → END
 * 
 * 并行逻辑封装在 DispatcherNode 内部：
 * - Planner 输出执行计划（哪些Worker、是否有依赖）
 * - Dispatcher 根据计划并行/串行执行Worker
 * - Synthesizer 汇总结果
 * 
 * 为什么不在Graph层面定义并行分支？
 * 因为并行组合是动态的（由LLM决定），编译期无法穷举所有组合。
 * 把并行逻辑放在DispatcherNode内部，用CompletableFuture实现运行时动态并行。
 */
@Slf4j
@Configuration
public class AgentGraphConfiguration {

    @Bean("compiledAgentGraph")
    public CompiledGraph compiledAgentGraph(DeepSeekChatModel chatModel,
                                            ArticleTool articleTool,
                                            BochaSearchTool bochaSearchTool,
                                            EsVectorStore esVectorStore,
                                            RedisComponent redisComponent) throws GraphStateException {

        StateGraph stateGraph = new StateGraph(new AgentStateFactory())
                // 注册节点
                .addNode("planner", node_async(new PlannerNode(chatModel)))
                .addNode("dispatcher", node_async(new DispatcherNode(
                        chatModel, articleTool, bochaSearchTool, esVectorStore, redisComponent)))
                .addNode("synthesizer", node_async(new SynthesizerNode(chatModel)))

                // 定义边：简洁的三节点链
                .addEdge(START, "planner")
                .addEdge("planner", "dispatcher")
                .addEdge("dispatcher", "synthesizer")
                .addEdge("synthesizer", END);

        log.info("Agent Graph（并行版）构建并编译完成");
        return stateGraph.compile();
    }
}
```


## 五、改造 AgentService

#### 设计讲解

AgentService 是对外暴露的服务层，Controller 调用它来处理用户请求。改造后的 AgentService 变得非常简洁——它不再直接持有 Tool 和 ChatClient，而是把所有逻辑委托给 Graph。

核心变化：
- **旧版**：AgentService 自己构建 messages、调用 chatClient、处理 Tool Calling、管理 RAG 检索
- **新版**：AgentService 只做三件事——准备输入、调用 `compiledGraph.invoke()`、提取结果

`AgentGraphConfiguration` 中直接调用 `stateGraph.compile()` 返回 `CompiledGraph` 作为 Bean。编译过程会验证拓扑的合法性（比如是否有孤立节点、是否有环等），编译后的 Graph 是不可变的，可以安全地被多线程并发调用。AgentService 直接注入 `CompiledGraph`，不需要额外的初始化步骤。

`RunnableConfig` 中的 `threadId` 用于标识一次执行。这里用会话ID作为 threadId，方便日志追踪和调试。

### 5.1 改造后的 AgentService

```java
package com.easyjob.agent.service;

import com.alibaba.cloud.ai.graph.CompiledGraph;
import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.RunnableConfig;
import com.easyjob.entity.AiMessage;
import com.easyjob.vo.AiChatVO;
import com.easyjob.vo.ArticleCardVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.util.*;

@Slf4j
@Service
public class AgentService {

    @Autowired
    @Qualifier("compiledAgentGraph")
    private CompiledGraph compiledGraph;

    @Autowired
    private AiConversationService aiConversationService;

    @Autowired
    private ImageUnderstandingService imageService;

    /**
     * 非流式聊天 - 通过 Graph 编排并行 Multi-Agent 协作
     * 
     * 执行流程：
     * 1. Planner 分析意图，输出执行计划（哪些Worker、是否并行）
     * 2. Dispatcher 根据计划并行/串行执行Worker
     * 3. Synthesizer 汇总结果（单Worker透传，多Worker用LLM汇总）
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

        // 3. 保存用户消息
        aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);

        // 4. 构建 Graph 输入
        Map<String, Object> input = new HashMap<>();
        input.put("userMessage", processedMessage);
        input.put("conversationId", finalConvId);
        input.put("userId", userId);

        // 从会话服务拉取历史消息，转为简单的 List<Map> 格式塞入 state
        List<AiMessage> history = aiConversationService.getContext(finalConvId);
        List<Map<String, String>> historyMaps = new ArrayList<>();
        for (AiMessage msg : history) {
            historyMaps.add(Map.of("role", msg.getRole(), "content", msg.getContent()));
        }
        input.put("historyMessages", historyMaps);

        // 5. 执行 Graph
        RunnableConfig config = RunnableConfig.builder()
                .threadId("conv-" + finalConvId)
                .build();

        Optional<OverAllState> result = compiledGraph.invoke(input, config);

        // 6. 提取结果
        String reply = result
                .map(s -> (String) s.value("finalReply").orElse("抱歉，处理出错了"))
                .orElse("抱歉，处理出错了");

        @SuppressWarnings("unchecked")
        List<ArticleCardVO> cards = result
                .map(s -> (List<ArticleCardVO>) s.value("articleCards").orElse(List.of()))
                .orElse(List.of());

        // 7. 保存AI回复
        aiConversationService.addMessage(finalConvId, userId, "assistant", reply, null,
                cards.isEmpty() ? null : cards);

        return AiChatVO.builder()
                .conversationId(String.valueOf(finalConvId))
                .reply(reply)
                .articles(cards)
                .build();
    }

    /**
     * 预处理用户消息（图片转文字）
     */
    private String preprocessMessage(String userMessage, List<String> imagePaths) {
        if (imagePaths == null || imagePaths.isEmpty()) {
            return userMessage;
        }
        StringBuilder processed = new StringBuilder();
        for (int i = 0; i < imagePaths.size(); i++) {
            String imageDescription = imageService.understandImage(imagePaths.get(i));
            processed.append(String.format("[图片%d内容：%s]\n", i + 1, imageDescription));
        }
        if (userMessage != null && !userMessage.isEmpty()) {
            processed.append("用户的问题：").append(userMessage);
        }
        return processed.toString();
    }
}
```

### 5.2 流式聊天（chatStream）— Synthesizer 流式方案

#### 设计讲解

流式输出在并行 Multi-Agent 架构下的核心矛盾：**前端只有一个 SSE 通道，但后端有多个 Worker 在并行产出内容**。你不能同时把 SearchWorker 和 WritingWorker 的流式输出混在一起发给前端——用户会看到两段内容交替出现，完全混乱。

**方案A（本方案）的策略**：Planner + Dispatcher 阶段同步执行（这部分涉及 Tool Calling 和多 Worker 并行，无法逐字流式），只在最终输出阶段做流式。

**关键设计决策：chatStream 不走 Graph，而是手动编排节点**

为什么？因为 `compiledGraph.invoke()` 是同步的，它会执行完所有节点（包括 Synthesizer）才返回。如果走 Graph，Synthesizer 已经同步执行完了，拿到的是完整的 `finalReply` 字符串，没有流式可言。

所以 `chatStream` 的策略是：
1. 手动调用 `PlannerNode.apply(state)` → 拿到执行计划
2. 手动调用 `DispatcherNode.apply(state)` → 拿到所有 Worker 结果
3. **不调用 SynthesizerNode**，而是在 Service 层用 `ChatClient.stream()` 做流式汇总

这样前两步同步执行（用户等待），第三步真正流式输出（用户看到逐字生成）。

**两种流式模式**：
- **单 Worker 透传**：只有一个 Worker 结果，直接把结果文本逐字发出（不调 LLM，用字符分片模拟流式）
- **多 Worker 汇总**：多个 Worker 结果，用 `ChatClient.stream()` 调 LLM 流式汇总

**为什么单 Worker 不直接一次性发出？**

虽然单 Worker 的结果已经是完整文本，但如果一次性发出，前端会瞬间显示一大段文字，没有"逐字生成"的体验。所以用字符分片（每次发几个字符）模拟流式效果，让用户体验一致。

**关于 OverAllState 的手动构建**：

不走 Graph 意味着没有框架帮你管理 state。所以需要手动构建一个 `Map<String, Object>` 作为 state 的替代品，在节点之间传递数据。PlannerNode 和 DispatcherNode 的 `apply()` 方法接收 `OverAllState`，所以需要手动创建 `OverAllState` 实例并填充数据。

`OverAllState` 的构造需要 `AgentStateFactory` 提供的 `KeyStrategy` 映射，然后通过 `OverAllState.updateState()` 方法写入数据。

#### 5.2.1 AgentService 新增 chatStream 方法

```java
/**
 * 流式聊天 - 手动编排 Planner → Dispatcher，Synthesizer 阶段流式输出
 *
 * 执行流程：
 * 1. 同步执行 Planner（分析意图，输出执行计划）
 * 2. 同步执行 Dispatcher（并行/串行执行 Worker）
 * 3. 流式输出最终结果：
 *    - 单Worker：字符分片逐字发出（不调LLM）
 *    - 多Worker：ChatClient.stream() 流式汇总
 *
 * 为什么不走 Graph？
 * compiledGraph.invoke() 是同步的，会执行完所有节点才返回。
 * 如果走 Graph，Synthesizer 已经同步完成，拿到的是完整字符串，没有流式可言。
 * 手动编排可以在 Synthesizer 阶段切换为流式调用。
 */
public Flux<String> chatStream(Long conversationId, Long userId,
                                String userMessage, List<String> imagePaths) {
    // 1. 创建或获取会话
    final Long finalConvId = conversationId != null ? conversationId
            : aiConversationService.createConversation(userId);

    // 2. 图片转文字
    String processedMessage = preprocessMessage(userMessage, imagePaths);

    // 3. 保存用户消息
    aiConversationService.addMessage(finalConvId, userId, "user", userMessage, imagePaths, null);

    // 4. 构建历史消息
    List<AiMessage> history = aiConversationService.getContext(finalConvId);
    List<Map<String, String>> historyMaps = new ArrayList<>();
    for (AiMessage msg : history) {
        historyMaps.add(Map.of("role", msg.getRole(), "content", msg.getContent()));
    }

    // 用于在流结束后保存完整回复和文章卡片
    StringBuilder fullReply = new StringBuilder();
    AtomicReference<List<ArticleCardVO>> articleCardsRef = new AtomicReference<>(List.of());

    return Flux.concat(
            // 先发送会话ID
            Flux.just("__CONV_ID__:" + finalConvId),

            // 同步执行 Planner + Dispatcher，然后流式输出
            Flux.create(sink -> {
                try {
                    // === 同步阶段：手动编排 Planner → Dispatcher ===

                    // 构建 OverAllState（手动模拟 Graph 的 state 管理）
                    OverAllState state = buildState(Map.of(
                            "userMessage", processedMessage,
                            "conversationId", finalConvId,
                            "userId", userId,
                            "historyMessages", historyMaps
                    ));

                    // 执行 Planner
                    PlannerNode planner = new PlannerNode(chatModel);
                    Map<String, Object> plannerOutput = planner.apply(state);
                    // 将 Planner 输出合并到 state
                    state = mergeState(state, plannerOutput);

                    log.info("chatStream Planner完成, activeWorkers: {}", plannerOutput.get("activeWorkers"));

                    // 执行 Dispatcher（内部并行执行 Worker）
                    DispatcherNode dispatcher = new DispatcherNode(
                            chatModel, articleTool, bochaSearchTool, esVectorStore, redisComponent);
                    Map<String, Object> dispatcherOutput = dispatcher.apply(state);

                    // 提取 Worker 结果
                    @SuppressWarnings("unchecked")
                    List<Map<String, String>> workerResults =
                            (List<Map<String, String>>) dispatcherOutput.getOrDefault("workerResults", List.of());
                    @SuppressWarnings("unchecked")
                    List<ArticleCardVO> cards =
                            (List<ArticleCardVO>) dispatcherOutput.getOrDefault("articleCards", List.of());
                    articleCardsRef.set(cards);

                    log.info("chatStream Dispatcher完成, workerResults数: {}, 卡片数: {}",
                            workerResults.size(), cards.size());

                    // === 流式阶段：根据 Worker 数量选择策略 ===

                    if (workerResults.size() <= 1) {
                        // 单Worker透传：字符分片逐字发出
                        String result = workerResults.isEmpty() ? "抱歉，处理出错了"
                                : workerResults.get(0).get("result");
                        streamByChunks(result, sink, fullReply);
                    } else {
                        // 多Worker汇总：ChatClient.stream() 流式输出
                        streamSynthesize(processedMessage, workerResults, sink, fullReply);
                    }
                } catch (Exception e) {
                    log.error("chatStream执行失败", e);
                    sink.next("[ERROR] 处理失败，请稍后重试");
                    sink.complete();
                }
            }),

            // 流结束后追加文章卡片 + 保存回复
            Flux.defer(() -> {
                // 保存AI回复
                List<ArticleCardVO> cards = articleCardsRef.get();
                aiConversationService.addMessage(finalConvId, userId, "assistant",
                        fullReply.toString(), null, cards.isEmpty() ? null : cards);

                // 发送文章卡片
                if (!cards.isEmpty()) {
                    String json = JSON.toJSONString(cards);
                    return Flux.just("__ARTICLES__:" + json);
                }
                return Flux.empty();
            })
    );
}

/**
 * 字符分片流式输出（单Worker透传场景）
 * 
 * 将完整文本按固定大小分片，逐片发送给前端，模拟逐字生成效果。
 * 不调用LLM，纯文本分片，延迟极低。
 */
private void streamByChunks(String text, FluxSink<String> sink, StringBuilder fullReply) {
    final int chunkSize = 5;  // 每次发5个字符
    for (int i = 0; i < text.length(); i += chunkSize) {
        String chunk = text.substring(i, Math.min(i + chunkSize, text.length()));
        sink.next(chunk);
    }
    fullReply.append(text);
    sink.complete();
}

/**
 * LLM流式汇总（多Worker场景）
 * 
 * 用 ChatClient.stream() 调用LLM，将多个Worker的结果整合为一个连贯的回复，
 * 并逐字流式输出给前端。
 */
private void streamSynthesize(String userMessage, List<Map<String, String>> workerResults,
                               FluxSink<String> sink, StringBuilder fullReply) {
    // 构建汇总 prompt（和 SynthesizerNode 的 prompt 保持一致）
    StringBuilder resultsText = new StringBuilder();
    for (Map<String, String> wr : workerResults) {
        resultsText.append(String.format("\n--- %s 的结果 ---\n%s\n",
                wr.get("workerName"), wr.get("result")));
    }

    String synthesizePrompt = """
            你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。
            
            【要求】
            - 不要简单拼接，要有逻辑地组织内容
            - 保留关键信息，去除重复内容
            - 使用清晰的结构（标题、列表等）
            - 语言自然流畅，像是一个人在回答
            - 不要提及"专家"、"Worker"、"任务"等内部概念
            
            【用户原始问题】
            %s
            
            【各专家的工作结果】
            %s
            """.formatted(userMessage, resultsText.toString());

    // 流式调用 LLM 汇总
    ChatClient synthesizer = ChatClient.builder(chatModel).build();
    Flux<String> stream = synthesizer.prompt()
            .user(synthesizePrompt)
            .stream()
            .content();

    // 阻塞式消费流（因为我们在 Flux.create 的 lambda 中，需要同步消费）
    stream.doOnNext(chunk -> {
        fullReply.append(chunk);
        sink.next(chunk);
    }).doOnComplete(sink::complete)
      .doOnError(e -> {
          log.error("流式汇总失败", e);
          sink.next("[ERROR] 汇总失败");
          sink.complete();
      }).blockLast();  // 阻塞等待流完成
}
```

> **关键代码解读**：
>
> 1. **手动编排 vs Graph 执行**：`chatStream` 不调用 `compiledGraph.invoke()`，而是手动 `new PlannerNode()` 和 `new DispatcherNode()` 并调用 `apply()`。这样可以在 Dispatcher 执行完后切换为流式输出，而不是等 Synthesizer 同步完成
>
> 2. **buildState / mergeState**：手动构建和合并 `OverAllState`。因为不走 Graph 框架，需要自己管理 state 的创建和数据合并。具体实现见下方
>
> 3. **streamByChunks**：单 Worker 场景的字符分片。每次发5个字符，前端收到后逐步拼接显示，模拟逐字生成效果。不调 LLM，延迟极低
>
> 4. **streamSynthesize**：多 Worker 场景的 LLM 流式汇总。用 `ChatClient.stream().content()` 获取 `Flux<String>`，然后用 `blockLast()` 阻塞消费。每收到一个 chunk 就通过 `sink.next()` 发给前端
>
> 5. **blockLast() 的使用**：因为我们在 `Flux.create` 的 lambda 中（同步上下文），需要阻塞等待 LLM 流完成。`blockLast()` 会阻塞当前线程直到流结束，期间每个 chunk 通过 `doOnNext` 实时发送给 sink
>
> 6. **文章卡片**：从 Dispatcher 的输出中提取 `articleCards`，通过 `AtomicReference` 传递到 `Flux.defer` 中，在流结束后追加 `__ARTICLES__:` 数据
>
> 7. **前端完全不需要改**：SSE 协议不变（`__CONV_ID__` → 流式文本 → `__ARTICLES__`），前端的 `streamChat` 函数无需任何修改

#### 5.2.2 AgentService 新增辅助方法（buildState / mergeState）

```java
/**
 * 手动构建 OverAllState（用于 chatStream 手动编排场景）
 * 
 * 因为 chatStream 不走 Graph 框架，需要手动创建 OverAllState 实例。
 * OverAllState 的构造需要 AgentStateFactory 提供的 KeyStrategy 映射。
 */
private OverAllState buildState(Map<String, Object> input) {
    AgentStateFactory factory = new AgentStateFactory();
    Map<String, KeyStrategy> strategies = factory.apply();
    OverAllState state = new OverAllState(strategies);
    state.withInputs(input);
    return state;
}

/**
 * 将节点输出合并到 OverAllState（模拟 Graph 框架的 state 合并逻辑）
 * 
 * Graph 框架中，节点 apply() 返回的 Map 会自动按 KeyStrategy 合并到 state。
 * 手动编排时需要自己调用 updateState 来合并。
 */
private OverAllState mergeState(OverAllState state, Map<String, Object> nodeOutput) {
    state.updateState(nodeOutput);
    return state;
}
```

> **注意**：`OverAllState` 的 `withInputs()` 和 `updateState()` 是 Spring AI Alibaba Graph 框架提供的方法。`withInputs()` 用于初始化输入数据，`updateState()` 用于按 KeyStrategy 合并节点输出。如果框架 API 有变化，请参考官方文档调整。

#### 5.2.3 AgentService 新增依赖字段

chatStream 手动编排需要直接使用 ChatModel、Tool 和组件，所以 AgentService 需要注入这些依赖：

```java
@Slf4j
@Service
public class AgentService {

    @Autowired
    @Qualifier("compiledAgentGraph")
    private CompiledGraph compiledGraph;

    @Autowired
    private AiConversationService aiConversationService;

    @Autowired
    private ImageUnderstandingService imageService;

    // === 以下字段仅 chatStream 手动编排使用 ===

    @Autowired
    private DeepSeekChatModel chatModel;  // 【新增】chatStream 手动创建节点需要

    @Autowired
    private ArticleTool articleTool;  // 【新增】chatStream 创建 DispatcherNode 需要

    @Autowired
    private BochaSearchTool bochaSearchTool;  // 【新增】

    @Autowired
    private EsVectorStore esVectorStore;  // 【新增】

    @Autowired
    private RedisComponent redisComponent;  // 【新增】

    // ... chat() 方法不变 ...
}
```

> **为什么 chat() 不需要这些字段但 chatStream() 需要？**
>
> `chat()` 走 Graph 框架，所有依赖在 `AgentGraphConfiguration` 中注入给各节点，AgentService 只需要 `compiledGraph`。
> `chatStream()` 手动编排，需要自己创建 PlannerNode 和 DispatcherNode 实例，所以需要直接持有这些依赖。
>
> 这是方案A的一个小缺点——AgentService 的依赖变多了。方案B（全链路流式）通过改造 Graph 框架的执行方式来避免这个问题，详见 `13-stream-plan-b.md`。

#### 5.2.4 新增 import

chatStream 方法需要额外的 import：

```java
import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.KeyStrategy;
import com.alibaba.fastjson2.JSON;
import com.easyjob.agent.graph.node.PlannerNode;
import com.easyjob.agent.graph.node.DispatcherNode;
import com.easyjob.agent.graph.state.AgentStateFactory;
import com.easyjob.agent.tool.ArticleTool;
import com.easyjob.agent.tool.BochaSearchTool;
import com.easyjob.agent.component.EsVectorStore;
import com.easyjob.component.RedisComponent;
import com.easyjob.vo.ArticleCardVO;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.deepseek.DeepSeekChatModel;
import reactor.core.publisher.Flux;
import reactor.core.publisher.FluxSink;

import java.util.concurrent.atomic.AtomicReference;
```

#### 5.2.5 流式执行流程图

```
用户发送消息
    │
    ▼
AgentService.chatStream()
    │
    ├── Flux.just("__CONV_ID__:123")          ← 立即发送会话ID
    │
    ├── Flux.create(sink -> {                  ← 进入同步执行阶段
    │       │
    │       ├── PlannerNode.apply(state)       ← 同步：LLM分析意图（~1-2秒）
    │       │   └── 输出: activeWorkers, taskDescriptions
    │       │
    │       ├── DispatcherNode.apply(state)    ← 同步：Worker并行执行（~2-5秒）
    │       │   └── 输出: workerResults, articleCards
    │       │
    │       └── 流式输出阶段                    ← 开始逐字发送给前端
    │           │
    │           ├── 单Worker → streamByChunks()    字符分片，不调LLM
    │           │   └── sink.next("你") → sink.next("好！有") → sink.next("什么可") → ...
    │           │
    │           └── 多Worker → streamSynthesize()  ChatClient.stream() 流式汇总
    │               └── sink.next("根据") → sink.next("搜索结果") → sink.next("，以下是") → ...
    │   })
    │
    └── Flux.defer(() -> {                     ← 流结束后
            ├── 保存AI回复到数据库
            └── Flux.just("__ARTICLES__:...")   ← 发送文章卡片（如果有）
        })
```

**用户体验时间线**：
```
0s          ~1s              ~3s                    ~3.5s        ~8s
│           │                │                      │            │
▼           ▼                ▼                      ▼            ▼
发送消息    收到会话ID       等待中...               开始逐字显示   完成
            __CONV_ID__      (Planner+Dispatcher    流式文本      __ARTICLES__
                              同步执行中)
```

> **与旧版流式的体验对比**：
> - 旧版（单Agent流式）：发送后 ~1秒开始逐字输出（直接调 LLM stream）
> - 新版（Multi-Agent流式）：发送后 ~3秒开始逐字输出（Planner + Worker 同步执行后才开始流式）
> - 多出的等待时间是 Planner 规划 + Worker 执行的开销，这是 Multi-Agent 架构的固有成本
> - 但一旦开始流式输出，体验和旧版一样（逐字生成）

#### 5.2.6 Controller 不需要改动

`AgentController` 的 `chatStream` 接口已经调用 `agentService.chatStream()`，返回 `Flux<String>`，SSE 协议不变，无需任何修改。

#### 5.2.7 前端不需要改动

前端 `AiChat.vue` 的 `streamChat` 函数解析 SSE 的逻辑完全兼容：
- `__CONV_ID__:` → 设置会话ID ✓
- 普通文本 → 追加到消息内容 ✓
- `__ARTICLES__:` → 解析文章卡片 ✓
- `[ERROR]` → 显示错误 ✓

流式协议没有任何变化，前端零改动。

## 六、执行流程详解

> 这一节用具体场景走一遍完整的执行流程，帮助理解每个节点在做什么、数据怎么流转。

### 6.1 简单场景：用户说"你好"

这是最简单的场景，只需要一个 Worker。

```
1. START → planner
   AgentService 把 {userMessage: "你好", conversationId: 123, userId: 1, historyMessages: [...]} 写入 OverAllState
   
2. PlannerNode 执行
   读取 historyMessages（理解上下文）+ userMessage
   调用 LLM，prompt 中包含用户消息"你好"
   LLM 判断这是闲聊，输出 {"tasks": [{"worker": "chat", "task": "回复用户的问候"}]}
   PlannerNode 写入 state：
   - activeWorkers: ["chat"]
   - taskDescriptions: {"chat": "回复用户的问候"}
   
3. planner → dispatcher
   
4. DispatcherNode 执行
   读取 activeWorkers = ["chat"]，只有一个独立Worker
   创建 ChatWorkerNode 实例，同步执行（单Worker不需要并行）
   ChatWorkerNode 从 taskDescriptions 读取 task = "回复用户的问候"
   ChatWorkerNode 调用 LLM，返回"你好！有什么可以帮你的吗？"
   结果写入 workerResults: [{workerName: "chat", result: "你好！..."}]
   
5. dispatcher → synthesizer
   
6. SynthesizerNode 执行
   读取 workerResults，发现只有1个结果
   直接透传，不调LLM
   写入 finalReply: "你好！有什么可以帮你的吗？"
   
7. synthesizer → END
   AgentService 从 OverAllState 中取出 finalReply，返回给用户
```

LLM调用次数：2次（Planner 1次 + ChatWorker 1次）

### 6.2 搜索场景：用户说"搜几篇Java文章"

```
1. PlannerNode → LLM输出 {"tasks": [{"worker": "search", "task": "搜索Java相关的文章"}]}
   写入 taskDescriptions: {"search": "搜索Java相关的文章"}

2. DispatcherNode → 创建 SearchWorkerNode，执行：
   a. 从 taskDescriptions 读取任务："搜索Java相关的文章"
   b. RAG检索：用任务描述去ES向量库搜索相关文档片段，注入到system prompt
   c. LLM + Tool Calling：LLM决定调用 ArticleTool.searchArticles("Java")
   d. Tool执行：ArticleTool 调用 EsComponent 搜索ES，返回文章列表
   e. LLM整理：把Tool返回的原始数据整理成用户友好的格式
   f. 文章卡片：从Redis获取文章卡片数据，写入 articleCards
   
3. SynthesizerNode → 单Worker，透传
```

LLM调用次数：2次（Planner + SearchWorker）+ Tool Calling 内部可能多次LLM调用（LLM决定调哪个Tool、处理Tool返回结果）

### 6.3 并行场景：用户说"帮我搜Java文章，顺便帮我列个写作大纲"

这是并行执行的典型场景。搜索和写作之间没有依赖关系，可以同时执行。

```
1. PlannerNode → LLM分析出两个独立意图，输出：
   {"tasks": [
     {"worker": "search", "task": "搜索Java相关的文章"},
     {"worker": "writing", "task": "列一个Java技术文章的写作大纲"}
   ]}
   写入 taskDescriptions: {"search": "搜索Java相关的文章", "writing": "列一个Java技术文章的写作大纲"}

2. DispatcherNode → 识别到两个独立Worker，启动并行执行：
   
   线程1（SearchWorkerNode）：                线程2（WritingWorkerNode）：
   ┌─────────────────────────┐              ┌─────────────────────────┐
   │ 读取task:"搜索Java相关文章"│              │ 读取task:"列写作大纲"     │
   │ RAG检索                  │              │ 构建ChatClient           │
   │ LLM + ArticleTool搜索   │   同时执行    │ LLM生成写作大纲          │
   │ 整理搜索结果             │   ◄────►     │ 返回大纲文本             │
   │ 获取文章卡片             │              │                         │
   └─────────────────────────┘              └─────────────────────────┘
   耗时：~3秒（Tool Calling较慢）             耗时：~1.5秒（纯LLM较快）
   
   总耗时 = max(3秒, 1.5秒) = 3秒
   如果串行执行，总耗时 = 3 + 1.5 = 4.5秒，并行节省了1.5秒

3. SynthesizerNode → 检测到2个Worker结果，调用LLM汇总：
   输入：SearchWorker的搜索结果 + WritingWorker的大纲
   输出：一个连贯的回复，先展示搜索到的文章，再给出写作大纲建议
```

LLM调用次数：4次（Planner + Search + Writing 并行 + Synthesizer汇总）

> **注意 Worker 的输入差异**：SearchWorker 收到的是"搜索Java相关的文章"，WritingWorker 收到的是"列一个Java技术文章的写作大纲"。每个 Worker 拿到的是 Planner 为它定制的精简指令，而不是完整的原始消息"帮我搜Java文章，顺便帮我列个写作大纲"。这让每个 Worker 的 prompt 更聚焦，LLM 理解更准确。

### 6.4 依赖链场景：用户说"搜几篇Spring Boot文章并总结下"

这是依赖链场景。analysis 必须等 search 完成后才能执行，因为 analysis 需要读取 search 的结果。

```
1. PlannerNode → LLM识别出"搜索+分析"的复合意图，输出：
   {"tasks": [{"worker": "search_then_analysis", "task": "搜索Spring Boot相关文章，然后对搜索结果进行总结分析"}]}
   写入 taskDescriptions: {"search": "搜索Spring Boot相关文章...", "analysis": "搜索Spring Boot相关文章..."}
   （依赖链的 task 描述同时写入 search 和 analysis 两个 key）

2. DispatcherNode → 识别到依赖链（包含 _then_），按顺序串行执行：
   
   步骤1：SearchWorkerNode 执行
   ├── 从 taskDescriptions 读取 task："搜索Spring Boot相关文章..."
   ├── RAG检索 + Tool Calling 搜索文章
   ├── 结果写入 workerResults（追加）
   └── 结果同时写入 searchResult（供analysis读取）
   
   步骤2：AnalysisWorkerNode 执行
   ├── 从 taskDescriptions 读取 task："搜索Spring Boot相关文章，然后对搜索结果进行总结分析"
   ├── 从 OverAllState 读取 searchResult（SearchWorker写入的）
   ├── 组合输入："【前置搜索结果】...【分析任务】搜索Spring Boot相关文章，然后对搜索结果进行总结分析"
   ├── LLM基于搜索结果进行深度分析
   └── 结果写入 workerResults（追加）

3. SynthesizerNode → 检测到2个Worker结果（search + analysis），调用LLM汇总
```

LLM调用次数：4次（Planner + Search + Analysis + Synthesizer）

> 注意：这里 search 和 analysis 是串行的，不能并行。因为 analysis 的输入依赖 search 的输出。这就是 `_then_` 标记的意义。

### 6.5 混合场景：用户说"搜Java文章分析下，另外帮我写个大纲"

这是最复杂的场景——依赖链和独立Worker混合并行。

```
1. PlannerNode → 输出：
   {"tasks": [
     {"worker": "search_then_analysis", "task": "搜索Java相关文章并对搜索结果进行深度分析总结"},
     {"worker": "writing", "task": "列一个Java技术文章的写作大纲"}
   ]}
   写入 taskDescriptions: {
     "search": "搜索Java相关文章并对搜索结果进行深度分析总结",
     "analysis": "搜索Java相关文章并对搜索结果进行深度分析总结",
     "writing": "列一个Java技术文章的写作大纲"
   }

2. DispatcherNode → 启动两个并行线程：

   线程1（依赖链 search_then_analysis）：     线程2（独立 WritingWorker）：
   ┌──────────────────────────────┐          ┌─────────────────────────┐
   │ SearchWorkerNode 执行         │          │ WritingWorkerNode 执行   │
   │ ├── 读取task:"搜索Java文章..."│          │ ├── 读取task:"列写作大纲" │
   │ ├── RAG + Tool Calling       │          │ ├── LLM生成大纲          │
   │ └── 耗时 ~3秒                │  同时执行  │ └── 耗时 ~1.5秒         │
   │                              │  ◄────►  │                         │
   │ AnalysisWorkerNode 执行       │          │ （已完成，等待线程1）     │
   │ ├── 读取task + searchResult  │          │                         │
   │ ├── LLM深度分析              │          │                         │
   │ └── 耗时 ~2秒                │          │                         │
   └──────────────────────────────┘          └─────────────────────────┘
   线程1总耗时：3 + 2 = 5秒                    线程2总耗时：1.5秒
   
   总耗时 = max(5秒, 1.5秒) = 5秒
   如果全部串行：3 + 2 + 1.5 = 6.5秒，并行节省了1.5秒

3. SynthesizerNode → 汇总3个Worker结果（search + analysis + writing）
   LLM把搜索结果、分析总结、写作大纲整合成一个连贯的回复
```

LLM调用次数：5次（Planner + Search + Analysis + Writing + Synthesizer）

### 6.6 指代解析场景：用户说"帮我分析下第一篇"

这个场景展示了 Planner 注入历史消息的核心价值——**指代解析**。

```
历史消息：
  用户："搜几篇Java并发的文章"
  助手："找到以下文章：1.《Java并发编程实战》2.《深入理解JUC》..."

当前消息："帮我分析下第一篇"

1. PlannerNode 执行
   读取 historyMessages，看到之前搜了Java并发文章
   理解"第一篇"指的是《Java并发编程实战》
   输出：{"tasks": [{"worker": "search_then_analysis", "task": "获取《Java并发编程实战》的详细内容并进行深度分析，提取核心观点和技术要点"}]}
   
   注意：Planner 把模糊的"第一篇"解析成了具体的文章名称，写入 task 描述
   AnalysisWorker 不需要看历史消息就知道要分析哪篇文章

2. DispatcherNode → SearchWorker 搜索 → AnalysisWorker 分析

3. SynthesizerNode → 透传（只有依赖链，最终只有 analysis 的结果需要展示）
```

> 这就是"Planner 拿历史做战略地图，Worker 拿精简战术指令"的核心价值。如果 Worker 自己拿历史消息去理解"第一篇"，不仅浪费 token，还可能理解错误（因为 Worker 的 system prompt 是面向特定任务的，不擅长做指代解析）。

## 七、与旧版的调用次数对比

> 这张表帮你直观理解并行版的开销。核心结论：**简单场景零额外开销，复杂场景是纯增量能力**。

| 场景 | 旧版（串行单选） | 新版（并行协作） | 差异 |
|------|-----------------|-----------------|------|
| 简单闲聊 | 2次 | 2次 | 无差异，Planner 替代 Supervisor，开销一样 |
| 单Worker搜索 | 2次 | 2次 | 无差异 |
| 搜索+分析 | 不支持（只能选一个） | 4次 | 新增能力，旧版做不到 |
| 搜索+写作（并行） | 不支持 | 4次 | 新增能力，且并行节省时间 |
| 搜索分析+写作（混合） | 不支持 | 5次 | 新增能力，依赖链+并行混合 |

> 简单场景下两个版本开销一致。并行能力是纯增量，不影响简单场景的性能。
> 
> 多出来的 LLM 调用主要是 Synthesizer 汇总（多 Worker 时才触发）。单 Worker 时 Synthesizer 只做透传，不调 LLM，所以简单场景没有额外开销。

## 八、文件改动总结

> 对比旧版，文件变化不大。核心是用 PlannerNode + DispatcherNode 替代了旧版的 SupervisorNode + SupervisorDispatcher。

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `agent/graph/state/AgentStateFactory.java` | 全局状态定义。关键改动：新增 `taskDescriptions` 字段存储 Planner 为每个 Worker 定制的任务描述；`workerResults` 和 `articleCards` 用 AppendStrategy 支持并行写入 |
| 新增 | `agent/graph/node/PlannerNode.java` | 执行计划节点。替代旧版 SupervisorNode，输出结构化 JSON 执行计划（含 Worker 名称和定制任务描述），注入完整历史消息理解上下文 |
| 新增 | `agent/graph/node/DispatcherNode.java` | 并行调度节点。核心组件，用 CompletableFuture 实现运行时动态并行，Worker 通过 state 读取 taskDescriptions |
| 新增 | `agent/graph/node/SearchWorkerNode.java` | 搜索Worker。从 taskDescriptions 读取任务描述（不读取历史消息），用任务描述做 RAG 检索和 Tool Calling |
| 新增 | `agent/graph/node/AnalysisWorkerNode.java` | 分析Worker。从 taskDescriptions 读取任务描述 + 从 state 读取 searchResult 作为依赖输入 |
| 新增 | `agent/graph/node/WritingWorkerNode.java` | 写作Worker。从 taskDescriptions 读取任务描述（不读取历史消息） |
| 新增 | `agent/graph/node/ChatWorkerNode.java` | 聊天Worker。从 taskDescriptions 读取任务描述（不读取历史消息，Planner 已将指代解析后的清晰指令写入 task） |
| 新增 | `agent/graph/node/SynthesizerNode.java` | 智能汇总节点。关键改动：单Worker透传，多Worker用LLM汇总（旧版只有透传） |
| 新增 | `agent/graph/config/AgentGraphConfiguration.java` | Graph配置。拓扑从7节点简化为3节点链式结构 |
| 删除 | `agent/graph/edge/SupervisorDispatcher.java` | 旧版条件路由。被 DispatcherNode 替代，不再需要 |
| 删除 | `agent/graph/node/SupervisorNode.java` | 旧版单选路由。被 PlannerNode 替代 |
| 修改 | `agent/service/AgentService.java` | 改为调用 CompiledGraph。大幅简化，不再直接持有 Tool 和 ChatClient |
| 新增 | `pom.xml` | 添加 `spring-ai-alibaba-graph-core` 依赖 |
| 不动 | `agent/tool/ArticleTool.java` | Tool不变，被 SearchWorkerNode 和 AnalysisWorkerNode 引用 |
| 不动 | `agent/tool/BochaSearchTool.java` | Tool不变，被 SearchWorkerNode 引用 |
| 不动 | `agent/controller/AgentController.java` | Controller不变，仍然调用 AgentService |
| 不动 | 前端所有文件 | 前端不需要改动，SSE协议不变 |

## 九、架构设计思考

### 9.1 为什么用 DispatcherNode 而不是 Graph 原生并行分支？

#### 问题本质

Graph 框架的并行分支是**编译期静态定义**的——你需要在 `addConditionalEdges` 时穷举所有可能的并行组合。但我们的并行组合是**运行时动态决定**的（由 Planner LLM 输出），编译期无法预知。

#### 如果用原生并行分支会怎样？

需要为每种可能的组合定义一个复合节点或子图：

```java
// 需要穷举所有组合，不现实
Map.of(
    "chat", "chat",
    "search", "search",
    "search_and_writing", "search_and_writing_subgraph",  // 需要子图
    "search_and_chat", "search_and_chat_subgraph",
    "search_then_analysis", "search_then_analysis_subgraph",
    "search_then_analysis_and_writing", "...",  // 组合继续爆炸
    // ... 4个Worker的组合数 = 2^4 - 1 = 15种
)
```

4个 Worker 就有15种非空组合，再加上依赖链的变体，组合数更多。每新增一个 Worker，组合数翻倍。这完全不可维护。

#### DispatcherNode 方案的优势

- **运行时动态**：Planner 输出什么组合就执行什么组合，无需预定义
- **拓扑简洁**：Graph 层面只有三个节点，清晰易懂
- **并行可控**：用 CompletableFuture 精确控制并行和依赖关系
- **易于扩展**：新增 Worker 只需在 `createWorker()` 中加一个 case，不需要改 Graph 拓扑

### 9.2 Graph 框架在这里的价值

你可能会问：既然并行逻辑都在 DispatcherNode 内部了，Graph 框架还有什么用？

Graph 框架仍然提供了重要的基础设施：

1. **OverAllState 全局状态管理**：节点间数据共享不需要手动传参。Planner 写入 `activeWorkers`，Dispatcher 直接读取；SearchWorker 写入 `searchResult`，AnalysisWorker 直接读取。如果没有 OverAllState，你需要自己管理一个 Context 对象在各个方法之间传递

2. **KeyStrategy 策略**：AppendStrategy 自动处理并行写入的合并。如果自己实现，需要手动处理线程安全的列表合并

3. **生命周期管理**：Graph 的 compile → invoke 模式保证了拓扑的合法性验证（编译期检查）和执行的线程安全（运行期隔离）

4. **可视化**：可以导出 Mermaid/PlantUML 图，方便团队理解架构

5. **可扩展性**：后续可以加入 Human-in-the-loop（`interruptBefore`）、状态持久化（`MemorySaver`）等高级特性，这些都是 Graph 框架原生支持的

6. **标准化**：遵循 LangGraph 的设计范式。如果团队成员了解 Python 的 LangGraph，可以无缝理解这套 Java 实现

### 9.3 后续扩展方向

1. **Worker 动态注册**：通过 SPI 或 `@Component` 注解扫描自动发现 Worker，不需要在 `createWorker()` 中硬编码 switch-case。定义一个 `@WorkerNode(name="search")` 注解，启动时自动注册到 Worker 工厂

2. **Worker 超时控制**：给 CompletableFuture 加 `orTimeout(30, TimeUnit.SECONDS)`，防止某个 Worker 卡死（比如 Tool Calling 超时）拖慢整体。超时后返回降级结果，不影响其他并行 Worker

3. **Worker 重试机制**：某个 Worker 失败时自动重试一次（比如 LLM API 偶发超时）。可以用 `CompletableFuture.handle()` 捕获异常后重试

4. **流式优化**：将 Synthesizer 改为流式调用（`.stream().content()`），实现汇总阶段的逐字输出。单 Worker 场景下，跳过 Synthesizer 直接走 Worker 的流式输出

5. **Human-in-the-loop**：在 Planner 输出执行计划后暂停，通过 WebSocket 把计划推送给前端，让用户确认"是否按这个计划执行"。用户确认后再继续执行 Dispatcher

6. **执行计划可视化**：前端展示当前正在执行哪些 Worker、哪些已完成、哪些在等待。通过 SSE 推送执行状态更新，让用户看到 Multi-Agent 协作的过程
