package com.easyjob.vo;

import lombok.Builder;
import lombok.Data;

import java.util.List;

/**
 * AI聊天响应VO（非流式）
 */
@Data
@Builder
public class AiChatVO {
    
    /**
     * 会话ID
     */
    private String conversationId;
    
    /**
     * AI回复内容
     */
    private String reply;
    
    /**
     * 相关文章卡片（Tool执行时收集的）
     */
    private List<ArticleCardVO> articles;
}
