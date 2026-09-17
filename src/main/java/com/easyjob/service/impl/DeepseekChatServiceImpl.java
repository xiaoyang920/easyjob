package com.easyjob.service.impl;

import com.easyjob.service.AiChatService;
import org.springframework.stereotype.Service;

@Service
public class DeepseekChatServiceImpl implements AiChatService {
    @Override
    public String chat(String message) {
        return "";
    }

    @Override
    public String chatWithSystem(String systemPrompt, String userMessage) {
        return "";
    }
}
