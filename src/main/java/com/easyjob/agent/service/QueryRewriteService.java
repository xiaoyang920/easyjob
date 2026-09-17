package com.easyjob.agent.service;

import com.easyjob.dto.RewriteResult;
import com.easyjob.entity.AiMessage;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
public class QueryRewriteService {
    @Autowired
    @Qualifier("rewriteClient")
    private ChatClient rewriteClient;

    public RewriteResult rewrite(String taskInput,  List<AiMessage> historyMessages){
        List<Message> messages = new ArrayList<>();
        if(historyMessages != null&&!historyMessages.isEmpty()){
            int start = Math.max(0, historyMessages.size()-6);
            for(int i = start; i < historyMessages.size(); i++){
                AiMessage message = historyMessages.get(i);
                if(message.getRole().equals("user")){
                    messages.add(new UserMessage(message.getContent()));
                }else if(message.getRole().equals("assistant")){
                    messages.add(new AssistantMessage(message.getContent()));
                }
            }
        }
        messages.add(new UserMessage("原始查询: "+ taskInput));
        try {
            RewriteResult result = rewriteClient.prompt()
                    .messages(messages)
                    .call()
                    .entity(RewriteResult.class);
            // 校验结果，确保 semanticQueries 不为空
            if (result == null || result.getKeywords() == null || result.getSemanticQueries().isEmpty()) {
                return RewriteResult.fallback(taskInput);
            }
            log.info("Query重写完成: 原始='{}', 语义queries={}, 关键词={}",
                    truncate(taskInput, 50), result.getSemanticQueries(), result.getKeywords());
            return result;
        } catch (Exception e) {
            log.error("Query重写失败，降级使用原始query", e);
            return RewriteResult.fallback(taskInput);
        }
    }
    private String truncate(String text, int maxLen) {
        if (text == null) return "";
        return text.length() > maxLen ? text.substring(0, maxLen) + "..." : text;
    }

}
