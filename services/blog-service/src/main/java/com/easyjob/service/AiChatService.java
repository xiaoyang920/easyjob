package com.easyjob.service;

public interface AiChatService {
    String chat(String question);
    String chatWithSystem(String systemPrompt, String userMessage);
}
