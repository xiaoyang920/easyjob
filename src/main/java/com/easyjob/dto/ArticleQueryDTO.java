package com.easyjob.dto;

import lombok.Data;

import java.io.Serializable;

/**
 * 文章查询DTO（Data Transfer Object）
 * 用于接收文章列表查询条件
 */
@Data
public class ArticleQueryDTO implements Serializable {
    
    private static final long serialVersionUID = 1L;
    
    /**
     * 用户ID（查询指定用户的文章）
     */
    private String userId;
    
    /**
     * 分类ID
     */
    private String categoryId;
    
    /**
     * 关键词（搜索标题或内容）
     */
    private String keyword;
    
    /**
     * 标签
     */
    private String tag;
    
    /**
     * 状态：0.草稿 1.已发布 2.已下架
     */
    private Integer status;
    
    /**
     * 是否只查询置顶文章
     */
    private Boolean onlyTop;
    
    /**
     * 是否只查询精华文章
     */
    private Boolean onlyEssence;
    
    /**
     * 是否只查询原创文章
     */
    private Boolean onlyOriginal;
    
    /**
     * 排序字段：publishTime, viewCount, likeCount
     */
    private String orderBy;
    
    /**
     * 排序方向：asc, desc
     */
    private String orderDirection;
    
    /**
     * 当前页码（默认1）
     */
    private Integer page = 1;
    
    /**
     * 每页大小（默认10）
     */
    private Integer size = 10;
}
