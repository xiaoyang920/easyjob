package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文章实体类（PO - Persistent Object）
 * 对应数据库 article_info 表
 */
@Data
@TableName("article_info")
public class Article {
    
    /**
     * 文章ID（主键，雪花算法）
     */
    @TableId(type = IdType.ASSIGN_ID)
    private Long articleId;
    
    /**
     * 作者用户ID
     */
    private Long userId;
    
    /**
     * 文章标题
     */
    private String title;
    
    /**
     * 文章封面图URL
     */
    private String coverImage;
    
    /**
     * 文章摘要/简介
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
    private Long categoryId;
    
    /**
     * 标签（多个标签用逗号分隔）
     */
    private String tags;
    
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
     * 状态：0.草稿 1.已发布 2.已下架 3.审核中
     */
    private Integer status;
    
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
     * 发布时间
     */
    private LocalDateTime publishTime;
    
    /**
     * 创建时间
     */
    private LocalDateTime createTime;
    
    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
    
    /**
     * 删除标记：0.未删除 1.已删除
     */
    private Integer deleted;
}
