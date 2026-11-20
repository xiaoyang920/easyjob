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
    private java.util.Map<String,Object> article;
    private String replyToSenderName;
    private Integer replyToStatus;
    private String clientMessageId;
    
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
     * 消息类型：1=文本，2=图片，3=文章卡片，4=表情包表情
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
    /**
     * 发送者当前佩戴的聊天气泡（仅正常的文本消息），结构与 SpaceArtwork 的 JSON 一致
     */
    private java.util.Map<String, Object> senderBubble;
    /**
     * 消息附加数据（表情消息为 {artworkId, key}），只在服务端使用
     */
    @com.fasterxml.jackson.annotation.JsonIgnore
    private String extraData;
    /**
     * 表情消息解析后的表情：{artworkId, key, name, url}；表情包不存在时为 {available:false}
     */
    private java.util.Map<String, Object> sticker;
}
