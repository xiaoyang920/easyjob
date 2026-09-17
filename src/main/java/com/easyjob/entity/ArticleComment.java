package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 文章评论实体类
 * 采用两层评论结构（顶级评论 + 扁平化回复）
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@TableName("comment")
public class ArticleComment {
    
    /**
     * 评论ID（主键，雪花算法）
     */
    @TableId(type = IdType.ASSIGN_ID)
    private Long commentId;
    
    /**
     * 文章ID
     */
    private Long articleId;
    
    /**
     * 文章作者ID（用于消息通知）
     */
    private Long articleUserId;
    
    /**
     * 父评论ID：0表示顶级评论，非0表示回复评论（指向顶级评论）
     */
    private Long parentId;
    
    /**
     * 评论内容
     */
    private String content;
    
    /**
     * 评论配图URL
     */
    private String imgPath;
    
    // ========== 评论者信息（冗余）==========
    
    /**
     * 评论者ID
     */
    private Long userId;
    
    /**
     * 评论者昵称（冗余）
     */
    private String userNickName;
    
    /**
     * 评论者头像（冗余）
     */
    private String userAvatar;
    
    // ========== 被回复者信息（冗余）==========
    
    /**
     * 被回复用户ID
     */
    private Long replyUserId;
    
    /**
     * 被回复用户昵称（冗余）
     */
    private String replyNickName;
    
    /**
     * 被回复用户头像（冗余）
     */
    private String replyAvatar;
    
    // ========== 状态与统计 ==========
    
    /**
     * 是否置顶：0否 1是
     */
    private Integer topType;
    
    /**
     * 状态：0正常 1已删除 2审核中 3已折叠
     */
    private Integer status;
    
    /**
     * 点赞数
     */
    private Integer likeCount;
    
    /**
     * 回复数（仅顶级评论有效）
     */
    private Integer replyCount;
    
    // ========== 时间字段 ==========
    
    /**
     * 创建时间
     */
    private LocalDateTime createTime;
    
    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}
