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

import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class SynthesizerNode implements NodeAction {
    @Autowired
    @Qualifier("deepSeekChatModel")
    private ChatModel chatModel;

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