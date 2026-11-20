package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 会话成员实体类
 */
@Data
@NoArgsConstructor
@TableName("conversation_member")
public class ConversationMember {
    
    /**
     * 主键ID
     */
    @TableId(type = IdType.AUTO)
    private Long id;
    
    /**
     * 会话ID
     */
    private Long conversationId;
    
    /**
     * 用户ID
     */
    private Long userId;
    
    /**
     * 未读消息数
     */
    private Integer unreadCount;
    
    /**
     * 最后已读消息ID
     */
    private Long lastReadMessageId;
    
    /**
     * 是否免打扰：0=否，1=是
     */
    private Integer isMuted;
    
    /**
     * 是否置顶：0=否，1=是
     */
    private Integer isTop;
    
    /**
     * 是否删除会话：0=否，1=是
     */
    private Integer isDeleted;
    
    /**
     * 加入时间
     */
    private LocalDateTime joinTime;
    
    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}
