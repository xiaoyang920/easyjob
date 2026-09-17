package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@TableName("chat_message")
public class ChatMessage {
    @TableId(type = IdType.ASSIGN_ID)
    Long messageId;

    Long sessionId;

    Long fromUserId;

    Long toUserId;

    String content;

    Integer messageType;

    Integer isRead;

    LocalDateTime createTime;

}
