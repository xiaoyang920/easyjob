package com.easyjob.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.entity.Conversation;
import com.easyjob.mapper.ConversationMapper;
import com.easyjob.mapper.ConversationMemberMapper;
import com.easyjob.service.ConversationService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ConversationVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 会话Service实现类
 */
@Service
@Slf4j
public class ConversationServiceImpl extends ServiceImpl<ConversationMapper, Conversation> implements ConversationService {
    
    @Autowired
    private ConversationMapper conversationMapper;
    
    @Autowired
    private ConversationMemberMapper conversationMemberMapper;
    
    @Autowired private com.easyjob.service.SocialService social;
    /**
     * 获取会话列表
     * @return 会话列表
     */
    @Override
    public List<ConversationVO> getConversationList() {
        return social.conversations(UserContext.getUserId(),false);
    }
    /**
     * 创建或获取会话
     * @param targetUserId 目标用户ID
     * @return 会话信息
     */
    @Override
    @Transactional(rollbackFor = Exception.class, isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    public ConversationVO createOrGetConversation(Long targetUserId) {
        if(targetUserId==null)throw new com.easyjob.exception.BusinessException(400,"请选择用户");
        return social.open(UserContext.getUserId(),targetUserId);
    }


    /**
     * 标记会话已读
     * @param conversationId 会话ID
     */
    @Override
    public void markAsRead(Long conversationId) {
        social.read(conversationId,UserContext.getUserId(),null);
    }
    /**
     * 删除会话
     * @param conversationId 会话ID
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteConversation(Long conversationId) {
        Long userId = UserContext.getUserId();
        conversationId=social.canonical(conversationId);
        //检查是否是会话的成员
        boolean isMember = conversationMemberMapper.isMember(conversationId, userId);
        if (!isMember) {
            throw new RuntimeException("用户不是会话成员");
        }
        // 更新 ConversationMember 的 is_deleted = 1
        //    WHERE conversation_id = conversationId AND user_id = userId
        conversationMemberMapper.updateIsDeleted(conversationId, userId);
        final String id=conversationId.toString();
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization(){@Override public void afterCommit(){com.easyjob.config.ChatWebSocketHandler.sendToUser(userId,java.util.Map.of("type","social_update","conversationId",id));}});
    }
    
    @Override
    public void updateLastMessage(Long conversationId, Long messageId, String content) {
        // TODO: 实现更新最后消息逻辑
        // 1. 更新 Conversation 表：
        //    last_message_id = messageId
        //    last_message_content = content（截取前100字）
        //    last_message_time = now()
        conversationMapper.updateLastMessage(conversationId, messageId, content);
    }

    @Override
    public Integer getTotalUnreadCount() {
        return ((Number)social.summary(UserContext.getUserId()).get("messageUnread")).intValue();
    }

    @Override
    public Long getLastMessageId(Long conversationId) {
        return conversationMapper.getLastMessageId(conversationId);
    }
}
