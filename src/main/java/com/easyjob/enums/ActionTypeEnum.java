package com.easyjob.enums;

import lombok.Getter;

/**
 * 用户行为类型枚举
 */
@Getter
public enum ActionTypeEnum {
    
    /**
     * 评论点赞
     */
    COMMENT_LIKE(0, "评论点赞"),
    
    /**
     * 讨厌评论
     */
    COMMENT_DISLIKE(1, "讨厌评论"),
    
    /**
     * 文章点赞
     */
    ARTICLE_LIKE(2, "文章点赞"),
    
    /**
     * 文章收藏
     */
    ARTICLE_COLLECT(3, "文章收藏"),
    
    /**
     * 文章投币
     */
    ARTICLE_COIN(4, "文章投币"),

    /**
     * 文章分享
     */
    ARTICLE_SHARE(5, "文章分享"),
    /**
     * 评论分享
     */
    COMMENT_SHARE(6, "评论分享"),

    ARTICLE_VIEW(7, "文章浏览");
    
    private final Integer code;
    private final String desc;
    
    ActionTypeEnum(Integer code, String desc) {
        this.code = code;
        this.desc = desc;
    }
    
    /**
     * 根据 code 获取枚举
     */
    public static ActionTypeEnum getByCode(Integer code) {
        if (code == null) {
            return null;
        }
        for (ActionTypeEnum type : ActionTypeEnum.values()) {
            if (type.getCode().equals(code)) {
                return type;
            }
        }
        return null;
    }
}
