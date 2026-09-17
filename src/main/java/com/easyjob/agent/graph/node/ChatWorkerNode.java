package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.entity.AiMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class ChatWorkerNode implements NodeAction {
    @Autowired
    @Qualifier("deepSeekChatModel")
    private ChatModel chatModel;

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
            List<AiMessage> history = state.value("historyMessages", List.of());
            List<Message> messages = new ArrayList<>();
            for (AiMessage msg : history) {
                if ("user".equals(msg.getRole())) {
                    messages.add(new UserMessage(msg.getContent()));
                } else if ("assistant".equals(msg.getRole())) {
                    messages.add(new AssistantMessage(msg.getContent()));
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