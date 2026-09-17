package com.easyjob.vo;

import lombok.Data;

import java.util.List;

/**
 * 文章详情VO（View Object）
 * 用于文章详情页面展示
 */
@Data
public class ArticleDetailVO {
    
    /**
     * 文章ID（转为字符串避免JavaScript精度丢失）
     */
    private String articleId;
    
    /**
     * 作者用户ID（转为字符串）
     */
    private String userId;
    
    /**
     * 作者昵称
     */
    private String authorName;
    
    /**
     * 作者头像
     */
    private String authorAvatar;
    
    /**
     * 文章标题
     */
    private String title;
    
    /**
     * 封面图片URL
     */
    private String coverImage;
    
    /**
     * 文章摘要
     */
    private String summary;
    
    /**
     * 文章内容（富文本/Markdown）
     */
    private String content;
    
    /**
     * 内容类型：1.富文本 2.Markdown
     */
    private Integer contentType;
    
    /**
     * 分类ID
     */
    private String categoryId;
    
    /**
     * 分类名称
     */
    private String categoryName;
    
    /**
     * 分类对象
     */
    private CategoryVO category;
    
    /**
     * 标签列表
     */
    private List<TagVO> tags;
    
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
     * 分享数
     */
    private Integer shareCount;
    
    /**
     * 是否置顶：0.否 1.是
     */
    private Integer isTop;
    
    /**
     * 是否精华：0.否 1.是
     */
    private Integer isEssence;
    
    /**
     * 是否原创：0.否 1.是
     */
    private Integer isOriginal;
    
    /**
     * 发布时间（格式化为字符串）
     */
    private String publishTime;
    
    /**
     * 创建时间（格式化为字符串）
     */
    private String createTime;
    
    /**
     * 更新时间（格式化为字符串）
     */
    private String updateTime;
    
    /**
     * 当前用户是否已点赞
     */
    private Boolean hasLiked;
    
    /**
     * 当前用户是否已收藏
     */
    private Boolean hasCollected;
}
