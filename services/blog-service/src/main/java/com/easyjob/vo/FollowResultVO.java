package com.easyjob.vo;

import lombok.Data;
import java.time.LocalDateTime;

/**
 * 关注操作结果VO
 * 用于返回关注/取消关注操作的结果
 */
@Data
public class FollowResultVO {
    
    /**
     * 目标用户ID
     */
    private String userId;
    
    /**
     * 关注时间（关注操作时返回，取消关注时为null）
     */
    private LocalDateTime focusTime;
}
