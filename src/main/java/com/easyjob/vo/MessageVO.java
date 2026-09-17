package com.easyjob.vo;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 消息VO
 */
@Data
@NoArgsConstructor
public class MessageVO {
    
    /**
     * 消息ID
     */
    private String messageId;
    
    /**
     * 会话ID
     */
    private String conversationId;
    
    /**
     * 发送者ID
     */
    private String senderId;
    
    /**
     * 发送者昵称
     */
    private String senderName;
    
    /**
     * 发送者头像
     */
    private String senderAvatar;
    
    /**
     * 消息类型：1=文本，2=图片
     */
    private Integer messageType;
    
    /**
     * 消息内容
     */
    private String content;
    
    /**
     * 发送时间
     */
    private LocalDateTime createTime;
    
    /**
     * 状态：0=正常，1=撤回
     */
    private Integer status;
    
    /**
     * 回复的消息ID
     */
    private String replyToMessageId;
    
    /**
     * 回复的消息内容（截取前50字）
     */
    private String replyToContent;
}
