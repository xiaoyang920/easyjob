package com.easyjob.exception;

import lombok.Getter;

/**
 * 业务异常类
 * 用于业务逻辑中的异常情况
 */
@Getter
public class BusinessException extends RuntimeException {
    
    /**
     * 错误码
     */
    private Integer code;
    
    /**
     * 默认构造函数（错误码默认为400）
     * @param message 错误信息
     */
    public BusinessException(String message) {
        super(message);
        this.code = 400;
    }
    
    /**
     * 自定义错误码的构造函数
     * @param code 错误码
     * @param message 错误信息
     */
    public BusinessException(Integer code, String message) {
        super(message);
        this.code = code;
    }
    
    /**
     * 带原因的构造函数
     * @param message 错误信息
     * @param cause 原始异常
     */
    public BusinessException(String message, Throwable cause) {
        super(message, cause);
        this.code = 400;
    }
    
    /**
     * 完整的构造函数
     * @param code 错误码
     * @param message 错误信息
     * @param cause 原始异常
     */
    public BusinessException(Integer code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }
}
