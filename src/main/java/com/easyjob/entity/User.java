package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.time.LocalDateTime;
@Data
@TableName("user_info") // 指定表名
public class User {
    
    // 主键注解，使用雪花算法生成ID
    @TableId(type = IdType.ASSIGN_ID)
    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;
    
    /**
     * 昵称
     */
    private String nickName;
    
    /**
     * 头像
     */
    private String avatar;
    
    /**
     * 邮箱
     */
    private String email;
    
    /**
     * 密码
     */
    private String password;
    
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
    private LocalDateTime joinTime;
    
    /**
     * 最后登录时间
     */
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
     * 角色：1普通用户 2管理员（与当前登录及空间页面约定一致）
     */
    private Integer role;
}
