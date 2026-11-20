package com.easyjob.vo;

import lombok.Data;
import java.time.LocalDateTime;

/**
 * 关注状态VO
 * 用于返回关注状态信息
 */
@Data
public class FollowStatusVO {
    
    /**
     * 目标用户ID
     */
    private String userId;
    
    /**
     * 是否关注了该用户
     */
    private Boolean isFollowing;
    
    /**
     * 是否互相关注
     */
    private Boolean isMutual;
    
    /**
     * 关注时间
     */
    private LocalDateTime focusTime;
}
