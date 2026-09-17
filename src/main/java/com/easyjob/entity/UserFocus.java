package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户关注实体类
 * 对应数据库表：user_focus
 */
@Data
@TableName("user_focus")
public class UserFocus {
    

    
    /**
     * 用户ID（谁关注）
     */
    private Long userId;
    
    /**
     * 被关注的用户ID（关注了谁）
     */
    private Long focusUserId;
    
    /**
     * 关注时间
     */
    private LocalDateTime focusTime;
}
