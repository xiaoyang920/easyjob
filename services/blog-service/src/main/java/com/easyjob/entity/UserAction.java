package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户行为实体类（点赞、收藏、投币等）
 */
@Data
@TableName("user_action")
public class UserAction {
    
    /**
     * 自增ID
     */
    @TableId(type = IdType.AUTO)
    private Long actionId;
    
    /**
     * 文章ID
     */
    private Long articleId;
    
    /**
     * 文章作者用户ID
     */
    private Long articleUserId;
    
    /**
     * 评论ID（如果是针对评论的操作）
     */
    private  Long commentId;
    
    /**
     * 操作类型
     * 0: 评论点赞
     * 1: 讨厌评论
     * 2: 文章点赞
     * 3: 文章收藏
     * 4: 文章投币
     * 5: 文章分享
     * 6: 评论分享
     */
    private Integer actionType;
    
    /**
     * 数量（投币数量等）
     */
    private Integer actionCount;
    
    /**
     * 操作用户ID
     */
    private Long userId;
    
    /**
     * 操作时间
     */
    private LocalDateTime actionTime;
}
