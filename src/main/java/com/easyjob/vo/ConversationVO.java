package com.easyjob.vo;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 会话列表VO
 */
@Data
@NoArgsConstructor
public class ConversationVO {
    
    /**
     * 会话ID
     */
    private String conversationId;
    
    /**
     * 会话类型：1=单聊，2=群聊
     */
    private Integer conversationType;
    
    /**
     * 对方用户ID（单聊）
     */
    private String otherUserId;
    
    /**
     * 对方昵称（单聊）/ 群名称（群聊）
     */
    private String otherUserName;
    
    /**
     * 对方头像（单聊）/ 群头像（群聊）
     */
    private String otherUserAvatar;
    
    /**
     * 最后一条消息内容
     */
    private String lastMessage;
    
    /**
     * 最后消息时间
     */
    private LocalDateTime lastMessageTime;
    
    /**
     * 未读消息数
     */
    private Integer unreadCount;
    
    /**
     * 是否免打扰
     */
    private Boolean isMuted;
    
    /**
     * 是否置顶
     */
    private Boolean isTop;
}
