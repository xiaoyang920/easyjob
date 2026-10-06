package com.easyjob.agent.param;

import lombok.Data;
import java.util.List;

/**
 * AI聊天请求参数
 */
@Data
public class AiChatParam {
    private String requestId;
    
    /**
     * 会话ID（可选，新会话不传）
     */
    private Long conversationId;

    /**
     * 发起问答的文章（可选）；来源上下文，不限制后续检索范围。
     */
    private Long originArticleId;
    
    /**
     * 用户消息
     */
    private String message;
    
    /**
     * 图片路径列表（可选）
     */
    private List<String> imagePaths;

    /**
     * 聊天模式：normal=单Agent直接对话，agent=Multi-Agent Graph协作
     * 默认 normal
     */
    private String mode;
}
