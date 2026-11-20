package com.easyjob.vo;

import lombok.Data;

/**
 * 用户行为状态 VO
 * 返回给前端，显示当前用户对某篇文章/评论的操作状态
 */
@Data
public class UserActionVO {
    
    /**
     * 文章ID
     */
    private String articleId;
    
    /**
     * 评论ID
     */
    private Integer commentId;
    
    /**
     * 是否已点赞
     */
    private Boolean hasLiked;
    
    /**
     * 是否已收藏
     */
    private Boolean hasCollected;
    
    /**
     * 是否已投币
     */
    private Boolean hasCoin;
    
    /**
     * 投币数量
     */
    private Integer coinCount;
    
    /**
     * 点赞时间
     */
    private String likeTime;
    
    /**
     * 收藏时间
     */
    private String collectTime;
    
    /**
     * 投币时间
     */
    private String coinTime;
}
