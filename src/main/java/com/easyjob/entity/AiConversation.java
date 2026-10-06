package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * AI会话实体
 */
@Data
@TableName("ai_conversation")
public class AiConversation {
    
    /**
     * 会话ID (雪花ID)
     * 使用ToStringSerializer避免前端JS精度丢失
     */
    @TableId(type = IdType.ASSIGN_ID)
    @JsonSerialize(using = ToStringSerializer.class)
    private Long conversationId;
    
    /**
     * 用户ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;

    /** 发起会话的文章；普通会话为空。 */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long originArticleId;

    /** 展示用标题，由会话列表关联当前可读文章获取。 */
    @TableField(exist = false)
    private String originArticleTitle;
    
    /**
     * 会话标题
     */
    private String title;
    
    /**
     * 消息数量
     */
    private Integer messageCount;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
    
    /**
     * 状态: 1-正常 0-已删除
     */
    private Integer status;
}
