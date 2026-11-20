package com.easyjob.vo;

import lombok.Data;

import java.util.List;

/**
 * 文章列表VO（View Object）
 * 用于首页、推荐及个人空间文章列表展示
 */
@Data
public class ArticleListVO {
    private Integer requiredLevel;
    private Boolean readableNow;
    
    /**
     * 文章ID（转为字符串避免JavaScript精度丢失）
     */
    private String articleId;
    private String userId;
    private String categoryId;
    private String recommendationReason;
    
    /**
     * 文章标题
     */
    private String title;
    
    /**
     * 封面图片URL
     */
    private String coverImage;

    /** 作者昵称，供首页和推荐卡片展示。 */
    private String authorName;

    /** 作者头像URL。 */
    private String authorAvatar;
    
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
     * 发布时间（格式化为字符串，格式：yyyy-MM-dd）
     */
    private String publishTime;

    /**
     * 摘要
     */
    private String summary;
    
    /**
     * 创建时间
     */
    private String createTime;
    
    /**
     * 更新时间
     */
    private String updateTime;
    
    /**
     * 分类对象
     */
    private CategoryVO category;
    
    /**
     * 标签列表（最多显示3个）
     */
    private List<TagVO> tags;
}
