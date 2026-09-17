package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.easyjob.vo.ArticleCardVO;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

/**
 * AI消息实体
 */
@Data
@TableName(value = "ai_message", autoResultMap = true)
public class AiMessage {
    
    /**
     * 消息ID (雪花ID)
     */
    @TableId(type = IdType.ASSIGN_ID)
    @JsonSerialize(using = ToStringSerializer.class)
    private Long messageId;
    
    /**
     * 会话ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long conversationId;
    
    /**
     * 角色: user/assistant/system
     */
    private String role;
    
    /**
     * 消息内容
     */
    private String content;
    
    /**
     * Token数量
     */
    private Integer tokenCount;
    
    /**
     * 工具调用记录 (JSON)
     */
    private String toolCalls;

    /**
     * 图片路径列表 (JSON数组)
     * 使用 MyBatis-Plus 的 JacksonTypeHandler 自动转换
     */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private List<String> imagePaths;

    private LocalDateTime createTime;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private List<ArticleCardVO> articleCards;

    @JsonSerialize(using = ToStringSerializer.class)
    private Long draftArticleId;
}