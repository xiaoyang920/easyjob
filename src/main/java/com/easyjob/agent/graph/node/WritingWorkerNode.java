package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import java.util.HashMap;
import java.util.Map;

@Slf4j
@Component
public class WritingWorkerNode implements NodeAction {
    @Autowired
    @Qualifier("deepSeekChatModel")
    private  ChatModel chatModel;
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

    @Override
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