package com.easyjob.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.entity.Conversation;
import com.easyjob.entity.ConversationMember;
import com.easyjob.entity.User;
import com.easyjob.mapper.ConversationMapper;
import com.easyjob.mapper.ConversationMemberMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.ConversationService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ConversationVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
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
    
    @Autowired
    private UserMapper userMapper;
    /**
     * 获取会话列表
     * @return 会话列表
     */
    @Override
    public List<ConversationVO> getConversationList() {
        Long userId = UserContext.getUserId();
        // 1. 调用 conversationMapper.selectConversationList(userId)
        // 2. 返回结果
        return conversationMapper.selectConversationList(userId);
    }
    /**
     * 创建或获取会话
     * @param targetUserId 目标用户ID
     * @return 会话信息
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public ConversationVO createOrGetConversation(Long targetUserId) {
        Long currentUserId = UserContext.getUserId();
        User user = userMapper.selectById(targetUserId);
        if (user == null) {
            throw new RuntimeException("目标用户不存在，userId: " + targetUserId);
        }
        // 1. 查询是否已存在会话：conversationMapper.selectExistConversation(currentUserId, targetUserId)
        Long existConversationId = conversationMapper.selectExistConversation(currentUserId, targetUserId);
        ConversationVO conversationVO = new ConversationVO();
        // 2. 如果存在，查询并返回会话信息
        if (existConversationId != null) {
            //查询未读消息数量
            Integer unreadCount = conversationMapper.selectUnreadCount(existConversationId, currentUserId);
            Conversation conversation = conversationMapper.selectById(existConversationId);
            setVO(targetUserId, user, conversationVO, conversation);
            conversationVO.setUnreadCount(unreadCount);
        }else {
            // 3. 如果不存在：
            //    - 创建 Conversation 记录
            Conversation conversation = new Conversation();
            conversation.setCreatorId(currentUserId);
            conversation.setConversationType(1);
            conversation.setCreateTime(LocalDateTime.now());
            conversationMapper.insert(conversation);
            //    - 创建两条 ConversationMember 记录（当前用户和目标用户）
            createConversationMember(conversation, currentUserId);
            createConversationMember(conversation, targetUserId);
            //    - 返回会话信息（包含对方用户信息）
            setVO(targetUserId, user, conversationVO, conversation);
            conversationVO.setUnreadCount(0);
        }
        return conversationVO;
    }


    private void createConversationMember(Conversation conversation, Long targetUserId) {
        ConversationMember conversationMember2 = new ConversationMember();
        conversationMember2.setConversationId(conversation.getConversationId());
        conversationMember2.setUserId(targetUserId);
        conversationMember2.setUnreadCount(0);
        conversationMember2.setIsTop(0);
        conversationMember2.setIsDeleted(0);
        conversationMember2.setIsMuted(0);
        conversationMember2.setJoinTime(LocalDateTime.now());
        conversationMember2.setUpdateTime(LocalDateTime.now());
        conversationMemberMapper.insert(conversationMember2);
    }

    private void setVO(Long targetUserId, User user, ConversationVO conversationVO, Conversation conversation) {
        conversationVO.setConversationId(conversation.getConversationId().toString());
        conversationVO.setConversationType(conversation.getConversationType());
        conversationVO.setOtherUserId(targetUserId.toString());
        conversationVO.setOtherUserName(user.getNickName());
        conversationVO.setOtherUserAvatar(user.getAvatar());
        conversationVO.setLastMessage(conversation.getLastMessageContent());
        conversationVO.setLastMessageTime(conversation.getLastMessageTime());
    }
    /**
     * 标记会话已读
     * @param conversationId 会话ID
     */
    @Override
    public void markAsRead(Long conversationId) {
        Long userId = UserContext.getUserId();
        // TODO: 实现标记已读逻辑
        // 1. 验证用户是会话成员
        boolean isMember = conversationMemberMapper.isMember(conversationId, userId);
        if (!isMember) {
            throw new RuntimeException("用户不是会话成员");
        }
        // 2. 调用 conversationMemberMapper.clearUnreadCount(conversationId, userId)
        conversationMemberMapper.clearUnreadCount(conversationId, userId);
        com.easyjob.config.ChatWebSocketHandler.sendToUser(userId,java.util.Map.of("type","unread_update","conversationId",conversationId.toString(),"unreadCount",0));
    }
    /**
     * 删除会话
     * @param conversationId 会话ID
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteConversation(Long conversationId) {
        Long userId = UserContext.getUserId();
        //检查是否是会话的成员
        boolean isMember = conversationMemberMapper.isMember(conversationId, userId);
        if (!isMember) {
            throw new RuntimeException("用户不是会话成员");
        }
        // 更新 ConversationMember 的 is_deleted = 1
        //    WHERE conversation_id = conversationId AND user_id = userId
        conversationMemberMapper.updateIsDeleted(conversationId, userId);
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
        return conversationMemberMapper.selectTotalUnreadCount(UserContext.getUserId());
    }

    @Override
    public Long getLastMessageId(Long conversationId) {
        return conversationMapper.getLastMessageId(conversationId);
    }
}
