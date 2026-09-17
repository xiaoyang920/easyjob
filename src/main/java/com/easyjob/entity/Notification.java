package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("notification")
public class Notification {
    @JsonSerialize(using = ToStringSerializer.class)
    @TableId(type = IdType.ASSIGN_ID)
    private Long notificationId;
    /** 接收者 */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;
    /** 触发者 */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long senderId;
    /** 触发者昵称（冗余，快照） */
    private String senderNickname;
    /** 触发者头像（冗余，快照） */
    private String senderAvatar;
    /** 通知类型，见 NotificationTypeEnum */
    private Integer type;
    /** 关联文章ID（前端跳转用，关注类通知为 null） */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long articleId;
    /** 文章标题（冗余，关注类为 null） */
    private String articleTitle;
    /** 目标对象ID（评论ID/文章ID/被关注者ID） */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long targetId;
    /** 目标对象内容预览（评论内容前 100 字；非评论类为 null） */
    private String targetPreview;
    /** 通知动词文案，如 "赞了你的评论"、"关注了你" */
    private String content;
    /** 0未读 1已读 */
    private Integer isRead;
    private LocalDateTime createTime;
}
