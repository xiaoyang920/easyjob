package com.easyjob.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;

/**
 * 通知消息体：既作为 send() 的入参（业务方填字段），
 * 也作为 MQ 队列的传输对象。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class NotificationMessage implements Serializable {
    private Long notificationId;
    /** 接收者 */
    private Long userId;
    /** 触发者 */
    private Long senderId;
    /** 触发者昵称（冗余快照） */
    private String senderNickname;
    /** 触发者头像（冗余快照） */
    private String senderAvatar;
    /** 通知类型，见 NotificationTypeEnum */
    private Integer type;
    /** 关联文章ID（前端跳转用） */
    private Long articleId;
    /** 文章标题（冗余快照） */
    private String articleTitle;
    /** 目标对象ID（评论ID/文章ID/被关注者ID） */
    private Long targetId;
    /** 目标对象内容预览（评论内容前 100 字） */
    private String targetPreview;
    /** 通知动词文案，如 "赞了你的评论" */
    private String content;
}
