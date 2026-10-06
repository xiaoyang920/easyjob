package com.easyjob.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 用户空间信息VO
 * 用于个人空间页面展示用户详细信息
 */
@Data
public class UserSpaceVO implements Serializable {
    private java.util.Map<String,Object> readingProgress;

    private static final long serialVersionUID = 1L;
    
    /**
     * 用户ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;
    
    /**
     * 昵称
     */
    private String nickName;
    
    /**
     * 头像URL
     */
    private String avatar;
    
    /**
     * 邮箱
     */
    private String email;
    
    /**
     * 性别：0.女 1.男 2.未知
     */
    private Integer sex;
    
    /**
     * 出生日期
     */
    private String birthday;
    
    /**
     * 个人简介
     */
    private String personIntroduction;
    
    /**
     * 加入日期
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    private LocalDateTime joinTime;
    
    /**
     * 最后登录时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
    private LocalDateTime lastLoginTime;
    
    /**
     * 最后登录IP
     */
    private String lastLoginIp;
    
    /**
     * 状态：0.禁用 1.正常
     */
    private Integer status;
    
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
     * 学校
     */
    private String school;
    
    /**
     * 空间公告
     */
    private String noticeInfo;
    
    /**
     * 硬币总数量
     */
    private Integer totalCoinCount;
    
    /**
     * 当前硬币数量
     */
    private Integer currentCoinCount;
    
    /**
     * 主题
     */
    private Integer theme;
    
    /**
     * 角色：1普通用户 2管理员（与当前应用约定一致）
     */
    private Integer role;
}
