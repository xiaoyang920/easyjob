package com.easyjob.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.entity.ConversationMember;
import com.easyjob.mapper.ConversationMemberMapper;
import com.easyjob.mapper.MessageMapper;
import com.easyjob.service.ConversationMemberService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * 会话成员Service实现类
 */
@Service
@Slf4j
public class ConversationMemberServiceImpl extends ServiceImpl<ConversationMemberMapper, ConversationMember> implements ConversationMemberService {
    
    @Autowired
    private ConversationMemberMapper conversationMemberMapper;
    @Autowired
    private MessageMapper messageMapper;

    /**
     * 检查用户是否是会话成员
     * @param conversationId 会话ID
     * @param userId 用户ID
     * @return
     */
    @Override
    public boolean isMember(Long conversationId, Long userId) {
        // 查询 ConversationMember 表，条件：conversation_id = conversationId AND user_id = userId AND is_deleted = 0
        return conversationMemberMapper.isMember(conversationId, userId);
    }
    
    @Override
    public void incrementUnreadCount(Long conversationId, Long excludeUserId) {
        // 调用 conversationMemberMapper.incrementUnreadCount(conversationId, excludeUserId)
        conversationMemberMapper.incrementUnreadCount(conversationId, excludeUserId);
    }
    
    @Override
    public void clearUnreadCount(Long conversationId, Long userId) {
        // TODO: 实现清空未读数
        // 调用 conversationMemberMapper.clearUnreadCount(conversationId, userId)
    }

    /**
     * 查询单聊中的receiveId
     * @param conversationId
     * @return
     */
    @Override
    public Long getOneReceiveId(Long conversationId,Long userId) {
        return conversationMemberMapper.selectOneReceiveId(conversationId, userId);
    }
}
