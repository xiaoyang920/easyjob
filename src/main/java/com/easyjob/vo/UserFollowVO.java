package com.easyjob.vo;

import lombok.Data;
import java.time.LocalDateTime;

/**
 * 粉丝/关注用户信息VO
 * 用于返回粉丝列表和关注列表
 */
@Data
public class UserFollowVO {
    
    /**
     * 用户ID
     */
    private String userId;
    
    /**
     * 昵称
     */
    private String nickName;
    
    /**
     * 头像
     */
    private String avatar;
    
    /**
     * 个人简介
     */
    private String personIntroduction;
    
    /**
     * 文章数
     */
    private Integer articleCount;
    
    /**
     * 粉丝数
     */
    private Integer followerCount;
    
    /**
     * 关注数
     */
    private Integer followingCount;
    
    /**
     * 当前用户是否关注了该用户
     */
    private Boolean isFollowing;
    
    /**
     * 关注时间
     */
    private LocalDateTime focusTime;
}
