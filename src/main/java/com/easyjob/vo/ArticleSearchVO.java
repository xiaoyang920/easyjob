package com.easyjob.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文章搜索结果VO
 */
@Data
public class ArticleSearchVO {
    
    /**
     * 文章ID
     */
    private String articleId;
    
    /**
     * 标题（可能包含高亮标签）
     */
    private String title;
    
    /**
     * 封面图片
     */
    private String coverImage;
    
    /**
     * 摘要
     */
    private String summary;
    
    /**
     * 标签
     */
    private String tags;
    
    /**
     * 是否原创：0-否 1-是
     */
    private Integer isOriginal;
    
    /**
     * 浏览次数
     */
    private Integer viewCount;
    
    /**
     * 点赞数
     */
    private Integer likeCount;
    
    /**
     * 收藏数
     */
    private Integer collectCount;
    
    /**
     * 评论数
     */
    private Integer commentCount;
    
    /**
     * 发布时间
     */
    private LocalDateTime publishTime;
    
    /**
     * 作者用户ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;
    
    /**
     * 作者昵称
     */
    private String authorName;
    
    /**
     * 作者头像
     */
    private String authorAvatar;
}
