package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.AiMessage;
import com.easyjob.entity.Conversation;
import com.easyjob.vo.ConversationVO;

import java.util.List;

/**
 * 会话Service接口
 */
public interface ConversationService extends IService<Conversation> {
    
    /**
     * 获取当前用户的会话列表
     * @return 会话列表
     */
    List<ConversationVO> getConversationList();
    
    /**
     * 创建或获取单聊会话
     * @param targetUserId 目标用户ID
     * @return 会话信息
     */
    ConversationVO createOrGetConversation(Long targetUserId);
    
    /**
     * 标记会话已读
     * @param conversationId 会话ID
     */
    void markAsRead(Long conversationId);
    
    /**
     * 删除会话（软删除）
     * @param conversationId 会话ID
     */
    void deleteConversation(Long conversationId);
    
    /**
     * 更新会话的最后消息
     * @param conversationId 会话ID
     * @param messageId 消息ID
     * @param content 消息内容
     */
    void updateLastMessage(Long conversationId, Long messageId, String content);

    Integer getTotalUnreadCount();

    Long getLastMessageId(Long conversationId);

}
