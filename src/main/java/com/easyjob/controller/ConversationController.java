package com.easyjob.controller;

import com.easyjob.dto.ConversationCreateDTO;
import com.easyjob.dto.MessageSendDTO;
import com.easyjob.service.ConversationService;
import com.easyjob.service.MessageService;
import com.easyjob.vo.ConversationVO;
import com.easyjob.vo.MessageListVO;
import com.easyjob.vo.MessageVO;
import com.easyjob.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 聊天Controller（新版）
 */
@RestController
@RequestMapping("/api/chat")
@Slf4j
public class ConversationController {
    
    @Autowired
    private ConversationService conversationService;
    
    @Autowired
    private MessageService messageService;
    
    /**
     * 获取会话列表
     * GET /api/chat/conversations
     */
    @GetMapping("/conversations")
    public ResponseVO<List<ConversationVO>> getConversations() {
        List<ConversationVO> list = conversationService.getConversationList();
        return ResponseVO.success(list);
    }
    
    /**
     * 创建/获取会话
     * POST /api/chat/conversation/create
     */
    @PostMapping("/conversation/create")
    public ResponseVO<ConversationVO> createConversation(@RequestBody ConversationCreateDTO dto) {
        ConversationVO vo = conversationService.createOrGetConversation(dto.getTargetUserId());
        return ResponseVO.success(vo);
    }
    
    /**
     * 获取消息列表
     * GET /api/chat/messages?conversationId=xxx&lastMessageId=xxx&size=20
     */
    @GetMapping("/messages")
    public ResponseVO<MessageListVO> getMessages(
            @RequestParam Long conversationId,
            @RequestParam(required = false) Long lastMessageId,
            @RequestParam(defaultValue = "20") Integer size) {
        MessageListVO vo = messageService.getMessageList(conversationId, lastMessageId, size);
        return ResponseVO.success(vo);
    }
    
    /**
     * 发送消息
     * POST /api/chat/message/send
     */
    @PostMapping("/message/send")
    public ResponseVO<MessageVO> sendMessage(@RequestBody MessageSendDTO dto) {
        MessageVO vo = messageService.sendMessage(dto);
        return ResponseVO.success(vo);
    }

    /**
     * 标记会话已读
     * POST /api/chat/conversation/{conversationId}/read
     */
    @PostMapping("/conversation/{conversationId}/read")
    public ResponseVO<Void> markAsRead(@PathVariable Long conversationId) {
        conversationService.markAsRead(conversationId);
        return ResponseVO.success("");
    }

    /**
     * 删除会话
     * POST /api/chat/conversation/{conversationId}/delete
     */
    @PostMapping("/conversation/{conversationId}/delete")
    public ResponseVO<Void> deleteConversation(@PathVariable Long conversationId) {
        conversationService.deleteConversation(conversationId);
        return ResponseVO.success("");
    }

    /**
     * 撤回消息
     * POST /api/chat/message/{messageId}/recall
     */
    @PostMapping("/message/{messageId}/recall")
    public ResponseVO<Void> recallMessage(@PathVariable Long messageId) {
        messageService.recallMessage(messageId);
        return ResponseVO.success("");
    }
    @GetMapping("/total-unread-count")
    public ResponseVO<Integer> getTotalUnreadCount() {
        Integer count = conversationService.getTotalUnreadCount();
        return ResponseVO.success(count);
    }

}
