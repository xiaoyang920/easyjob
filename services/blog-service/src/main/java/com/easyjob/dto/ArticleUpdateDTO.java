package com.easyjob.dto;

import lombok.Data;

import java.io.Serializable;

/**
 * 文章更新DTO（Data Transfer Object）
 * 用于接收前端更新文章的请求数据
 */
@Data
public class ArticleUpdateDTO implements Serializable {
    
    private static final long serialVersionUID = 1L;
    
    /**
     * 文章ID（必填，用于指定要更新的文章）
     */
    private String articleId;
    
    /**
     * 文章标题（可选，1-100字符）
     */
    private String title;
    
    /**
     * 文章封面图URL（可选）
     */
    private String coverImage;
    
    /**
     * 文章摘要（可选，最多500字符）
     */
    private String summary;
    
    /**
     * 文章内容（可选）
     */
    private String content;
    
    /**
     * 内容类型：1.富文本 2.Markdown
     */
    private Integer contentType;
    
    /**
     * 分类ID（可选）
     */
    private String categoryId;
    
    /**
     * 标签（多个标签用逗号分隔，可选）
     */
    private String tags;
    
    /**
     * 是否原创：0.否 1.是
     */
    private Integer isOriginal;
    
    /**
     * 状态：0.草稿 1.已发布 2.已下架
     */
    private Integer status;
    
    /**
     * 是否置顶：0.否 1.是
     */
    private Integer isTop;
    
    /**
     * 验证文章ID是否有效
     */
    public boolean isArticleIdValid() {
        return articleId != null && !articleId.trim().isEmpty();
    }
}
