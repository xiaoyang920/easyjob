package com.easyjob.controller;

import com.easyjob.service.impl.NotificationServiceImpl;
import com.easyjob.service.impl.SseEmitterService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/notification")
public class NotificationController {
    @Autowired
    private NotificationServiceImpl notificationService;
    @Autowired
    private SseEmitterService sseEmitterService;

    /**
     * 建立 SSE 连接（前端 EventSource 调用）
     */
    @GetMapping("/stream")
    public SseEmitter stream() {
        return sseEmitterService.connect(UserContext.getUserId());
    }

    /**
     * 获取未读消息列表
     */
    @GetMapping("/unread")
    public ResponseVO<?> getUnread() {
        return ResponseVO.success(notificationService.getUnread(UserContext.getUserId()));
    }

    /**
     * 获取未读数量（铃铛红点）
     */
    @GetMapping("/unread-count")
    public ResponseVO<?> unreadCount() {
        return ResponseVO.success(notificationService.getUnreadCount(UserContext.getUserId()));
    }

    /**
     * 分页获取所有消息
     */
    @GetMapping("/list")
    public ResponseVO<?> list(@RequestParam(defaultValue = "1") Integer page,
                              @RequestParam(defaultValue = "20") Integer size,
                              @RequestParam(required=false) Integer type,
                              @RequestParam(defaultValue="false") boolean unreadOnly) {
        return ResponseVO.success(notificationService.getAll(UserContext.getUserId(), page, size,type,unreadOnly));
    }

    /**
     * 标记单条已读
     */
    @PostMapping("/{notificationId}/read")
    public ResponseVO<?> markRead(@PathVariable Long notificationId) {
        notificationService.markAsRead(notificationId, UserContext.getUserId());
        return ResponseVO.success("已读");
    }

    /**
     * 全部标记已读
     */
    @PostMapping("/read-all")
    public ResponseVO<?> markAllRead() {
        notificationService.markAllAsRead(UserContext.getUserId());
        return ResponseVO.success("全部已读");
    }
}
