package com.easyjob.vo;

import lombok.Data;

/**
 * 评论返回VO（View Object）
 * 用于文章评论列表展示
 */
@Data
public class ArticleCommentVO {
    
    /**
     * 评论ID（转为字符串避免JavaScript精度丢失）
     */
    private String commentId;
    
    /**
     * 文章ID
     */
    private String articleId;
    
    /**
     * 父评论ID（0表示顶级评论，非0表示指向顶级评论）
     */
    private String parentId;
    
    /**
     * 评论内容
     */
    private String content;
    
    /**
     * 评论配图URL
     */
    private String imgPath;
    
    // ========== 评论者信息 ==========
    
    /**
     * 评论者ID
     */
    private String userId;
    
    /**
     * 评论者昵称
     */
    private String userNickName;
    
    /**
     * 评论者头像
     */
    private String userAvatar;
    
    // ========== 被回复者信息 ==========
    
    /**
     * 被回复用户ID（回复评论时有值）
     */
    private String replyUserId;
    
    /**
     * 被回复用户昵称
     */
    private String replyNickName;
    
    /**
     * 被回复用户头像
     */
    private String replyAvatar;
    
    // ========== 状态与统计 ==========
    
    /**
     * 是否置顶：0否 1是
     */
    private Integer topType;
    
    /**
     * 点赞数
     */
    private Integer likeCount;
    
    /**
     * 回复数（仅顶级评论有效）
     */
    private Integer replyCount;
    
    /**
     * 当前用户是否已点赞该评论
     */
    private Boolean hasLiked;
    
    /**
     * 当前用户是否已点踩该评论
     */
    private Boolean hasDisliked;
    
    // ========== 时间字段 ==========
    
    /**
     * 创建时间（格式化为字符串）
     */
    private String createTime;
    
    /**
     * 更新时间（格式化为字符串）
     */
    private String updateTime;
}
