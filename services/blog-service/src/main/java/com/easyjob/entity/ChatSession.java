package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@TableName("chat_session")
public class ChatSession {
    @TableId(type = IdType.ASSIGN_ID)
    Long sessionId;
    Long userId;
    Long otherUserId;
    String lastMessage;
    LocalDateTime lastMessageTime;
    Integer unreadCount;
    LocalDateTime updateTime;
}
