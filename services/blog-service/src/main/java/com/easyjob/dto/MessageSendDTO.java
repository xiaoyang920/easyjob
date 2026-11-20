package com.easyjob.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 发送消息请求DTO
 */
@Data
@NoArgsConstructor
public class MessageSendDTO {
    private Long articleId;
    private String clientMessageId;
    
    /**
     * 会话ID
     */
    private Long conversationId;
    
    /**
     * 消息类型：1=文本，2=图片，3=文章卡片，4=表情包表情
     */
    private Integer messageType;
    /**
     * 表情消息：所属表情包作品ID与表情编号（content 由服务端生成）
     */
    private String stickerPackId;
    private String stickerKey;
    
    /**
     * 消息内容
     */
    private String content;
    
    /**
     * 回复的消息ID（可选）
     */
    private Long replyToMessageId;
    
    /**
     * 发送者昵称（前端缓存传入，避免后端查询）
     */
    private String senderName;
    
    /**
     * 发送者头像（前端缓存传入，避免后端查询）
     */
    private String senderAvatar;
}
