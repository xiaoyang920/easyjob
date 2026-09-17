package com.easyjob.dto;

import com.alibaba.fastjson2.annotation.JSONField;
import com.easyjob.entity.Article;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * ES文档 - 文章
 */
@Data
@NoArgsConstructor
public class ArticleEsDTO {
    
    private Long articleId;
    
    private Long userId;
    
    private String title;
    
    private String coverImage;
    
    private String summary;
    
    private String content;
    
    private Integer contentType;
    
    private Long categoryId;
    
    private String tags;
    
    private Integer viewCount;
    
    private Integer likeCount;
    
    private Integer collectCount;
    
    private Integer commentCount;
    
    private Integer shareCount;
    
    private Integer status;
    
    private Integer isTop;
    
    private Integer isEssence;
    
    private Integer isOriginal;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime publishTime;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime createTime;

    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    @JSONField(format = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime updateTime;
    
    /**
     * 从 Article 实体转换
     */
    public ArticleEsDTO(Article article) {
        this.articleId = article.getArticleId();
        this.userId = article.getUserId();
        this.title = article.getTitle();
        this.coverImage = article.getCoverImage();
        this.summary = article.getSummary();
        this.content = article.getContent();
        this.contentType = article.getContentType();
        this.categoryId = article.getCategoryId();
        this.tags = article.getTags();
        this.viewCount = article.getViewCount();
        this.likeCount = article.getLikeCount();
        this.collectCount = article.getCollectCount();
        this.commentCount = article.getCommentCount();
        this.shareCount = article.getShareCount();
        this.status = article.getStatus();
        this.isTop = article.getIsTop();
        this.isEssence = article.getIsEssence();
        this.isOriginal = article.getIsOriginal();
        this.publishTime = article.getPublishTime();
        this.createTime = article.getCreateTime();
        this.updateTime = article.getUpdateTime();
    }
}
