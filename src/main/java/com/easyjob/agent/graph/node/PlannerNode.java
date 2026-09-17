package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.easyjob.entity.AiMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
@Slf4j
@Component
@RequiredArgsConstructor
public class PlannerNode implements NodeAction {

    private final ChatClient chatClient;

    private static final String PLANNER_PROMPT="""
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
    @Override
    public Map<String, Object> apply(OverAllState state) throws Exception {
        String userMessage = state.value("userMessage", "");
        List<AiMessage> history = state.value("historyMessages", List.of());
        // 构建带历史上下文的消息列表，让Planner能理解指代（如"帮我分析下第一篇"）
        // 只有 Planner 注入历史消息，Worker 不注入
        List<Message> messages = new ArrayList<>();
        for (AiMessage msg : history) {
            if ("user".equals(msg.getRole())) {
                messages.add(new UserMessage(msg.getContent()));
            } else if ("assistant".equals(msg.getRole())) {
                messages.add(new AssistantMessage(msg.getContent()));
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