package com.easyjob.config;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.ResponseVO;
import io.jsonwebtoken.JwtException;
import lombok.extern.slf4j.Slf4j;
import org.apache.catalina.connector.ClientAbortException;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.validation.BindException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.async.AsyncRequestNotUsableException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import jakarta.servlet.http.HttpServletRequest;

/**
 * 全局异常处理器
 * 统一处理系统中的各种异常，返回统一格式的错误响应
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {
    
    /**
     * 业务异常处理
     * 用于处理业务逻辑中主动抛出的异常
     */
    @ExceptionHandler(BusinessException.class)
    public ResponseVO<?> handleBusinessException(BusinessException e, HttpServletRequest request) {
        log.warn("业务异常 [{}]: code={}, message={}", request.getRequestURI(), e.getCode(), e.getMessage());
        return ResponseVO.error(e.getCode(), e.getMessage());
    }
    
    /**
     * 参数校验异常处理 - @Valid 注解校验失败
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseVO<?> handleValidException(MethodArgumentNotValidException e, HttpServletRequest request) {
        String message = e.getBindingResult().getFieldError() != null 
            ? e.getBindingResult().getFieldError().getDefaultMessage() 
            : "参数校验失败";
        log.warn("参数校验失败 [{}]: {}", request.getRequestURI(), message);
        return ResponseVO.error(400, message);
    }
    
    /**
     * 参数绑定异常处理
     */
    @ExceptionHandler(BindException.class)
    public ResponseVO<?> handleBindException(BindException e, HttpServletRequest request) {
        String message = e.getBindingResult().getFieldError() != null 
            ? e.getBindingResult().getFieldError().getDefaultMessage() 
            : "参数绑定失败";
        log.warn("参数绑定异常 [{}]: {}", request.getRequestURI(), message);
        return ResponseVO.error(400, message);
    }
    
    /**
     * JWT异常处理
     * 处理token过期、无效等情况
     */
    @ExceptionHandler(JwtException.class)
    public ResponseVO<?> handleJwtException(JwtException e, HttpServletRequest request) {
        log.warn("Token异常 [{}]: {}", request.getRequestURI(), e.getMessage());
        return ResponseVO.error(401, "登录已过期，请重新登录");
    }
    
    /**
     * 数据库异常处理
     */
    @ExceptionHandler(DataAccessException.class)
    public ResponseVO<?> handleDataAccessException(DataAccessException e, HttpServletRequest request) {
        log.error("数据库异常 [{}]", request.getRequestURI(), e);
        return ResponseVO.error(500, "数据操作失败，请稍后重试");
    }
    
    /**
     * 数据库唯一约束冲突
     */
    @ExceptionHandler(DuplicateKeyException.class)
    public ResponseVO<?> handleDuplicateKeyException(DuplicateKeyException e, HttpServletRequest request) {
        log.warn("唯一约束冲突 [{}]: {}", request.getRequestURI(), e.getMessage());
        return ResponseVO.error(400, "数据已存在，请勿重复操作");
    }
    
    /**
     * 文件上传大小超限异常
     */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseVO<?> handleMaxUploadSizeExceededException(MaxUploadSizeExceededException e, HttpServletRequest request) {
        log.warn("文件上传超限 [{}]: {}", request.getRequestURI(), e.getMessage());
        return ResponseVO.error(400, "文件大小超过限制，请上传小于5MB的文件");
    }
    
    /**
     * 空指针异常
     */
    @ExceptionHandler(NullPointerException.class)
    public ResponseVO<?> handleNullPointerException(NullPointerException e, HttpServletRequest request) {
        log.error("空指针异常 [{}]", request.getRequestURI(), e);
        return ResponseVO.error(500, "系统异常，请联系管理员");
    }
    
    /**
     * 非法参数异常
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseVO<?> handleIllegalArgumentException(IllegalArgumentException e, HttpServletRequest request) {
        log.warn("非法参数异常 [{}]: {}", request.getRequestURI(), e.getMessage());
        return ResponseVO.error(400, e.getMessage());
    }
    
    /**
     * 客户端断开连接（主要发生在 SSE/长连接场景：前端切页、关浏览器、断网）
     * 这时候后端继续往响应流写数据会抛 IOException / ClientAbortException，
     * Spring 会包成 AsyncRequestNotUsableException 冒上来。
     * 此时连接已经关了，没法再返回任何响应体，所以返回 null 让 Spring 直接跳过，
     * 避免二次报错（content-type 冲突之类）。
     */
    @ExceptionHandler({AsyncRequestNotUsableException.class, ClientAbortException.class})
    public Object handleClientAbort(Exception e, HttpServletRequest request) {
        // 用 debug 级别，避免日志噪音；需要排查时单独调高
        log.debug("客户端断开连接 [{}]: {}", request.getRequestURI(), e.getMessage());
        return null;
    }

    /**
     * 未知异常处理
     * 捕获所有未被上面处理的异常
     */
    @ExceptionHandler(Exception.class)
    public ResponseVO<?> handleException(Exception e, HttpServletRequest request) {
        log.error("系统异常 [{}]", request.getRequestURI(), e);
        return ResponseVO.error(500, "系统繁忙，请稍后重试");
    }
}
