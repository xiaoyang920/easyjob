package com.easyjob.controller;

import com.easyjob.service.UserActionService;
import com.easyjob.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/action")
@Slf4j
public class UserActionController {
    @Autowired
    private UserActionService userActionService;
    /**
     * 点赞文章
     */
    @PostMapping("/article/{articleId}/like")
    public ResponseVO<?> like(@PathVariable Long articleId, @RequestParam(required=false) Boolean active) {
        return ResponseVO.success(userActionService.like(articleId, active));
    }
    /**
     * 收藏文章
     */
    @PostMapping("/article/{articleId}/collect")
    public ResponseVO<?> collect(@PathVariable Long articleId, @RequestParam(required=false) Boolean active) {
        return ResponseVO.success(userActionService.collect(articleId, active));
    }
    /**
     * 获取用户收藏列表
     */
    @GetMapping("/user/{userId}/collect")
    public ResponseVO<?> getUserCollect(@PathVariable Long userId, 
                                        @RequestParam(defaultValue = "1") Integer page, 
                                        @RequestParam(defaultValue = "20") Integer size,
                                        Integer type,
                                        @RequestParam(defaultValue = "latest") String order) {
        return ResponseVO.success(userActionService.getUserCollect(userId, page, size, type, order));
    }
    /**
     * 获取用户点赞列表
     */
    @GetMapping("/user/{userId}/like")
    public ResponseVO<?> getUserLike(@PathVariable Long userId, 
                                     @RequestParam(defaultValue = "1") Integer page, 
                                     @RequestParam(defaultValue = "20") Integer size,
                                     Integer type,
                                     @RequestParam(defaultValue = "latest") String order) {
        return ResponseVO.success(userActionService.getUserLike(userId, page, size, type, order));
    }
}
