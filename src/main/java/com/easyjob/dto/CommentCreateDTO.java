package com.easyjob.dto;

import lombok.Data;

import java.io.Serializable;

/**
 * 评论创建DTO（Data Transfer Object）
 * 用于接收前端发布评论的请求数据
 */
@Data
public class CommentCreateDTO implements Serializable {
    
    private static final long serialVersionUID = 1L;
    
    /**
     * 文章ID（必填）
     */
    private Long articleId;
    
    /**
     * 文章作者ID（必填，用于消息通知）
     */
    private Long articleUserId;
    
    /**
     * 评论文字（最多500字符；配图评论允许为空）
     */
    private String content;
    
    /**
     * 评论配图URL（可选，通过上传接口获得）
     */
    private String imgPath;
    /** Optional top-level comment anchored to selected article text. */
    private CommentQuote quote;
    
    /**
     * 父评论ID（可选，0或不传表示顶级评论）
     */
    private Long parentId;
    
    /**
     * 被回复用户ID（可选，回复评论时传）
     */
    private Long replyUserId;
    
    /**
     * 验证评论内容是否有效
     */
    public boolean isContentValid() {
        int length = content == null ? 0 : content.trim().length();
        return length <= 500 && (length > 0 || (imgPath != null && !imgPath.isBlank()));
    }
    
    /**
     * 判断是否为顶级评论
     */
    public boolean isTopLevelComment() {
        return parentId == null || parentId == 0;
    }
}
