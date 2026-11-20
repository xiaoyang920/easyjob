package com.easyjob.vo;

import lombok.Data;

/**
 * 统一返回结果类
 */
@Data
public class ResponseVO<T> {
    
    // 状态：success 或 error
    private String status;
    
    // 状态码
    private Integer code;
    
    // 消息
    private String message;
    
    // 数据
    private T data;
    
    // 私有构造函数
    private ResponseVO() {
    }
    
    private ResponseVO(String status, Integer code, String message, T data) {
        this.status = status;
        this.code = code;
        this.message = message;
        this.data = data;
    }
    
    /**
     * 成功返回（带数据）
     */
    public static <T> ResponseVO<T> success(T data) {
        return new ResponseVO<>("success", 200, "操作成功", data);
    }
    
    /**
     * 成功返回（带数据和自定义消息）
     */
    public static <T> ResponseVO<T> success(String message, T data) {
        return new ResponseVO<>("success", 200, message, data);
    }
    
    /**
     * 成功返回（无数据）
     */
    public static <T> ResponseVO<T> success(String message) {
        return new ResponseVO<>("success", 200, message, null);
    }
    
    /**
     * 失败返回
     */
    public static <T> ResponseVO<T> error(Integer code, String message) {
        return new ResponseVO<>("error", code, message, null);
    }
    
    /**
     * 失败返回（默认400状态码）
     */
    public static <T> ResponseVO<T> error(String message) {
        return new ResponseVO<>("error", 400, message, null);
    }
}
