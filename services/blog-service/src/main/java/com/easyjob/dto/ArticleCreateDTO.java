package com.easyjob.dto;

import lombok.Data;

import java.io.Serializable;
import java.util.List;

/**
 * 文章创建/编辑DTO（Data Transfer Object）
 * 用于接收前端创建或编辑文章的请求数据
 */
@Data
public class ArticleCreateDTO implements Serializable {
    /** Stable identity of the first editor save; retries must not create duplicate drafts. */
    private String clientRequestId;
    // Current workspace identity plus content lock. Zero revision is only for legacy publications.
    private String expectedRevisionId;
    private Long expectedLockVersion;
    
    private static final long serialVersionUID = 1L;
    
    /**
     * 文章标题（必填，1-100字符）
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
     * 文章内容（必填）
     */
    private String content;
    
    /**
     * 内容类型：1.富文本 2.Markdown（默认1）
     */
    private Integer contentType = 1;
    
    /**
     * 分类ID（可选）
     */
    private String categoryId;
    
    /**
     * 标签（多个标签用逗号分隔，可选）- 兼容旧版
     */
    private String tags;
    
    /**
     * 标签名列表（新版，前端传数组）
     */
    private List<String> tagNames;
    
    /**
     * 是否原创：0.否 1.是（默认1）
     */
    private Integer isOriginal = 1;
    
    /**
     * 保存意图：0.保存版本草稿 1.提交审核；不能直接指定公开状态
     */
    private Integer status;
    
    /**
     * 验证标题是否有效
     */
    public boolean isTitleValid() {
        return title != null 
            && title.trim().length() >= 1 
            && title.trim().length() <= 100;
    }
    
    /**
     * 验证内容是否有效
     */
    public boolean isContentValid() {
        return content != null && content.trim().length() > 0;
    }
}
