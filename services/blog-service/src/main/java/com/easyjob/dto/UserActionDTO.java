package com.easyjob.dto;

import lombok.Data;

/**
 * 用户行为操作 DTO
 * 用于接收前端的点赞、收藏、投币等操作请求
 */
@Data
public class UserActionDTO {
    
    /**
     * 文章ID
     */
    private String articleId;
    
    /**
     * 评论ID（针对评论的操作时传入）
     */
    private Integer commentId;
    
    /**
     * 操作类型
     * 0: 评论点赞
     * 1: 讨厌评论
     * 2: 文章点赞
     * 3: 文章收藏
     * 4: 文章投币
     */
    private Integer actionType;
    
    /**
     * 操作数量（投币数量，默认为1）
     */
    private Integer actionCount = 1;
    
    /**
     * 操作动作（true: 添加操作，false: 取消操作）
     */
    private Boolean action;
}
