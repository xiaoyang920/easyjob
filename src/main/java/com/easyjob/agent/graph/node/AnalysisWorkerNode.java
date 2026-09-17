package com.easyjob.agent.graph.node;

import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.easyjob.agent.tool.ArticleTool;
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
public class AnalysisWorkerNode implements NodeAction {
    @Autowired
    @Qualifier("deepSeekChatModel")
    private  ChatModel chatModel;
    @Autowired
    private  ArticleTool articleTool;

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
    @Override
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