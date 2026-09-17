package com.easyjob.enums;

import lombok.Getter;

/**
 * 通知类型枚举
 */
@Getter
public enum NotificationTypeEnum {
    /** 评论/回复（评论了你的文章、回复了你的评论，统一归为一类） */
    COMMENT_REPLY(1, "评论/回复"),
    /** 点赞（文章被赞） */
    LIKE(2, "点赞"),
    /** 收藏（文章被收藏） */
    COLLECT(3, "收藏"),
    /** 关注（被人关注） */
    FOLLOW(4, "关注"),
    /** 系统通知 */
    SYSTEM(5, "系统");

    private final Integer code;
    private final String desc;

    NotificationTypeEnum(Integer code, String desc) {
        this.code = code;
        this.desc = desc;
    }
}
