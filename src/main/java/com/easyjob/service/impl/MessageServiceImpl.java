package com.easyjob.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.dto.MessageSendDTO;
import com.easyjob.entity.Message;
import com.easyjob.entity.User;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.MessageMapper;
import com.easyjob.service.ConversationMemberService;
import com.easyjob.service.ConversationService;
import com.easyjob.service.MessageService;
import com.easyjob.service.UserService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.MessageListVO;
import com.easyjob.vo.MessageVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 消息Service实现类
 */
@Service
@Slf4j
public class MessageServiceImpl extends ServiceImpl<MessageMapper, Message> implements MessageService {
    
    @Autowired
    private MessageMapper messageMapper;
    
    @Autowired
    private ConversationService conversationService;
    
    @Autowired
    private ConversationMemberService conversationMemberService;

    @Autowired
    private UserService userService;
    @Autowired
    private com.easyjob.mapper.ConversationMapper conversationMapper;

    private void afterCommit(Runnable push) {
        if (!org.springframework.transaction.support.TransactionSynchronizationManager.isSynchronizationActive())
            throw new IllegalStateException("Message push requires transaction synchronization");
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
            new org.springframework.transaction.support.TransactionSynchronization() {
                @Override public void afterCommit() {
                    try { push.run(); } catch (Exception error) { log.warn("消息已保存，推送失败，客户端可补拉", error); }
                }
            });
    }

    private MessageVO toVO(Message message, User sender) {
        MessageVO vo = new MessageVO();
        vo.setMessageId(message.getMessageId().toString());
        vo.setConversationId(message.getConversationId().toString());
        vo.setSenderId(message.getSenderId().toString());
        vo.setClientMessageId(message.getClientMessageId());
        vo.setContent(message.getContent()); vo.setMessageType(message.getMessageType());
        vo.setStatus(message.getStatus()); vo.setCreateTime(message.getCreateTime());
        vo.setReplyToMessageId(message.getReplyToMessageId() == null ? null : message.getReplyToMessageId().toString());
        vo.setSenderName(sender.getNickName()); vo.setSenderAvatar(sender.getAvatar());
        return vo;
    }

    private int pageSize(Integer size) {
        if (size == null || size < 1 || size > 100) throw new BusinessException(400, "分页范围无效");
        return size;
    }

    @Override public MessageListVO getMessagesAfter(Long cid, Long after, Integer size) {
        pageSize(size);
        if (after == null || after < 0) throw new BusinessException(400, "消息游标无效");
        if (!conversationMemberService.isMember(cid, UserContext.getUserId())) throw new BusinessException(403, "用户不是会话成员");
        var rows = messageMapper.selectMessagesAfter(cid, after, size + 1);
        var result = new MessageListVO(); result.setHasMore(rows.size() > size);
        result.setRecords(rows.subList(0, Math.min(size, rows.size()))); return result;
    }
    /**
     * 获取消息列表
     * @param conversationId 会话ID
     * @param lastMessageId 最后一条消息ID
     * @param size 获取数量
     * @return 消息列表
     */
    @Override
    public MessageListVO getMessageList(Long conversationId, Long lastMessageId, Integer size) {
        pageSize(size);
        Long userId = UserContext.getUserId();
        // 1. 验证用户是会话成员：conversationMemberService.isMember(conversationId, userId)
        boolean isMember = conversationMemberService.isMember(conversationId, userId);
        if (!isMember) {
            throw new BusinessException("用户不是会话成员");
        }
        // 2. 查询消息：messageMapper.selectMessageList(conversationId, lastMessageId, size + 1)
        //    多查一条用于判断是否还有更多
        List<MessageVO> messageList = messageMapper.selectMessageList(conversationId, lastMessageId, size + 1);
        // 3. 构建 MessageListVO 返回
        //    - records: 实际返回的消息列表（最多 size 条）
        //    - hasMore: 查询结果是否超过 size 条
        MessageListVO messageListVO = new MessageListVO();
        messageListVO.setRecords(messageList.subList(0, Math.min(size, messageList.size())));
        messageListVO.setHasMore(messageList.size() > size);
        return messageListVO;
    }
    /**
     * 发送消息
     * @param dto 发送消息参数
     * @return 发送的消息
     */
    @Override
    @Transactional(rollbackFor = Exception.class, isolation = org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    public MessageVO sendMessage(MessageSendDTO dto) {
        Long userId = UserContext.getUserId();
        // 1. 验证用户是会话成员
        boolean isMember = conversationMemberService.isMember(dto.getConversationId(), userId);
        if (!isMember) {
            throw new BusinessException("用户不是会话成员");
        }
        if (dto.getConversationId() == null || dto.getContent() == null || dto.getContent().isBlank()
                || dto.getContent().length() > 10000 || !java.util.Set.of(1, 2).contains(dto.getMessageType() == null ? 0 : dto.getMessageType()))
            throw new BusinessException(400, "消息内容或类型无效");
        String key = dto.getClientMessageId();
        if (key == null) key = java.util.UUID.randomUUID().toString();
        if (!key.matches("[A-Za-z0-9_-]{16,64}")) throw new BusinessException(400, "消息幂等键无效");
        if (conversationMapper.lockConversation(dto.getConversationId()) == null) throw new BusinessException(404, "会话不存在");
        User sender = userService.getById(userId);
        if (sender == null) throw new BusinessException(403, "用户不存在");
        Message previous = messageMapper.findClientMessage(userId, key);
        if (previous != null) {
            if (!java.util.Objects.equals(previous.getConversationId(), dto.getConversationId())
                    || !java.util.Objects.equals(previous.getContent(), dto.getContent())
                    || !java.util.Objects.equals(previous.getMessageType(), dto.getMessageType())
                    || !java.util.Objects.equals(previous.getReplyToMessageId(), dto.getReplyToMessageId()))
                throw new BusinessException(409, "消息幂等键对应的内容不一致");
            return toVO(previous, sender);
        }
        if (dto.getReplyToMessageId() != null) {
            Message reply = messageMapper.selectById(dto.getReplyToMessageId());
            if (reply == null || !reply.getConversationId().equals(dto.getConversationId())) throw new BusinessException(400, "回复消息不属于当前会话");
        }
        // 2. 创建 Message 实体并保存
        Message message = new Message();
        message.setClientMessageId(key);
        message.setStatus(0);
        message.setMessageType(dto.getMessageType());
        message.setReplyToMessageId(dto.getReplyToMessageId());
        message.setContent(dto.getContent());
        message.setConversationId(dto.getConversationId());
        message.setSenderId(userId);
        message.setCreateTime(LocalDateTime.now());
        try {
            if (messageMapper.insert(message) != 1) throw new BusinessException("消息保存失败");
        } catch (org.springframework.dao.DuplicateKeyException duplicate) {
            throw new BusinessException(409, "消息幂等键已使用，请刷新会话后重试");
        }
        // 3. 更新会话最后消息：conversationService.updateLastMessage(...)
        conversationService.updateLastMessage(dto.getConversationId(), message.getMessageId(), message.getContent());
        // 4. 增加其他成员未读数：conversationMemberService.incrementUnreadCount(...)
        conversationMemberService.incrementUnreadCount(dto.getConversationId(), userId);
        // 5. 构建并返回 MessageVO
        MessageVO messageVO = toVO(message, sender);
        Long receiveId = conversationMemberService.getOneReceiveId(dto.getConversationId(), userId);
        Map<String, Object> wsMsg = new HashMap<>();
        wsMsg.put("type", "message");
        wsMsg.put("conversationId", messageVO.getConversationId()); wsMsg.put("messageId", messageVO.getMessageId());
        wsMsg.put("clientMessageId", messageVO.getClientMessageId());
        wsMsg.put("content", messageVO.getContent()); wsMsg.put("messageType", messageVO.getMessageType());
        wsMsg.put("senderId", messageVO.getSenderId()); wsMsg.put("senderName", sender.getNickName());
        wsMsg.put("senderAvatar", sender.getAvatar()); wsMsg.put("createTime", messageVO.getCreateTime().toString());
        wsMsg.put("status", 0); wsMsg.put("replyToMessageId", messageVO.getReplyToMessageId());
        afterCommit(() -> { if (receiveId != null) ChatWebSocketHandler.sendToUser(receiveId, wsMsg); });
        return messageVO;
    }
    
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void recallMessage(Long messageId) {
        Long userId = UserContext.getUserId();
        // 1. 查询消息
        Message message = messageMapper.selectById(messageId);
        if(BeanUtil.isEmpty(message)){
            throw new BusinessException("消息不存在");
        }
        conversationMapper.lockConversation(message.getConversationId());
        // 2. 验证是本人发送的消息
        if(!message.getSenderId().equals(userId)){
            throw new BusinessException("不能撤回非本人发送的消息");
        }
        // 3. 验证消息发送时间在2分钟内
        if(LocalDateTime.now().isAfter(message.getCreateTime().plusMinutes(2))){
            throw new BusinessException("消息发送时间超过2分钟，不能撤回");
        }
        // 4. 更新消息状态为撤回（status = 1）
        message.setStatus(1);
        messageMapper.updateById(message);
        // 5. 如果是会话最后一条消息，更新会话的 last_message_content = "[消息已撤回]"
        if(message.getMessageId().equals(conversationService.getLastMessageId(message.getConversationId()))){
            conversationService.updateLastMessage(message.getConversationId(), message.getMessageId(), "[消息已撤回]");
        }
        // websocket推送信息
        Long receiveId = conversationMemberService.getOneReceiveId(message.getConversationId(), userId);
        if(ChatWebSocketHandler.isOnline(receiveId)){
            Map<String, Object> wsMsg = new HashMap<>();
            wsMsg.put("type", "recall");
            wsMsg.put("conversationId", message.getConversationId().toString());
            wsMsg.put("messageId", messageId.toString());
            wsMsg.put("senderId", message.getSenderId().toString());
            wsMsg.put("content", message.getContent());  // 原消息内容，用于前端判断
            afterCommit(() -> ChatWebSocketHandler.sendToUser(receiveId, wsMsg));
        }
    }
}
