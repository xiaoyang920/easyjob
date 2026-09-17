package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 消息实体类
 */
@Data
@NoArgsConstructor
@TableName("message")
public class Message {
    
    /**
     * 消息ID
     */
    @TableId(type = IdType.ASSIGN_ID)
    private Long messageId;
    
    /**
     * 会话ID
     */
    private Long conversationId;
    
    /**
     * 发送者ID
     */
    private Long senderId;
    
    /**
     * 消息类型：1=文本，2=图片，3=语音，4=视频，5=文件
     */
    private Integer messageType;
    
    /**
     * 消息内容
     */
    private String content;
    
    /**
     * 扩展数据（JSON格式，图片尺寸、文件大小等）
     */
    private String extraData;
    
    /**
     * 回复的消息ID
     */
    private Long replyToMessageId;
    
    /**
     * 消息状态：0=正常，1=撤回，2=删除
     */
    private Integer status;
    
    /**
     * 创建时间
     */
    private LocalDateTime createTime;
}
