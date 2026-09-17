package com.easyjob.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 创建会话请求DTO
 */
@Data
@NoArgsConstructor
public class ConversationCreateDTO {
    
    /**
     * 目标用户ID（单聊时使用）
     */
    private Long targetUserId;
}
