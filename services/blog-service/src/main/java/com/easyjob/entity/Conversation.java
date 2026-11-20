package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 会话实体类
 */
@Data
@NoArgsConstructor
@TableName("conversation")
public class Conversation {
    
    /**
     * 会话ID
     */
    @TableId(type = IdType.ASSIGN_ID)
    private Long conversationId;
    
    /**
     * 会话类型：1=单聊，2=群聊
     */
    private Integer conversationType;
    
    /**
     * 群名称（群聊时使用）
     */
    private String groupName;
    
    /**
     * 群头像（群聊时使用）
     */
    private String groupAvatar;
    
    /**
     * 创建者ID
     */
    private Long creatorId;
    
    /**
     * 最后一条消息ID
     */
    private Long lastMessageId;
    
    /**
     * 最后一条消息内容（冗余字段）
     */
    private String lastMessageContent;
    
    /**
     * 最后消息时间
     */
    private LocalDateTime lastMessageTime;
    
    /**
     * 创建时间
     */
    private LocalDateTime createTime;
    
    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}
