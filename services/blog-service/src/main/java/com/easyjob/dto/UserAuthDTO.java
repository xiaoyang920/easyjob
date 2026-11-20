package com.easyjob.dto;

import lombok.Data;

import java.io.Serializable;

/**
 * 用户认证请求DTO
 * 用于登录和注册
 */
@Data
public class UserAuthDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 昵称（注册时必填，登录时不需要）
     */
    private String nickName;

    /**
     * 邮箱（登录和注册都需要）
     */
    private String email;

    /**
     * 密码（登录和注册都需要）
     */
    private String password;

    /**
     * 确认密码（注册时可选，用于前端二次验证）
     */
    private String confirmPassword;

    /**
     * 验证码（注册时必填）
     */
    private String code;

    // 默认构造函数
    public UserAuthDTO() {
    }

    /**
     * 登录构造函数
     */
    public UserAuthDTO(String email, String password) {
        this.email = email;
        this.password = password;
    }

    /**
     * 注册构造函数
     */
    public UserAuthDTO(String nickName, String email, String password) {
        this.nickName = nickName;
        this.email = email;
        this.password = password;
    }
}
