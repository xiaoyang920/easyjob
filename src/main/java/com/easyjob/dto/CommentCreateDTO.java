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
     * 评论内容（必填，1-500字符）
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
        return content != null 
            && content.trim().length() >= 1 
            && content.trim().length() <= 500;
    }
    
    /**
     * 判断是否为顶级评论
     */
    public boolean isTopLevelComment() {
        return parentId == null || parentId == 0;
    }
}
