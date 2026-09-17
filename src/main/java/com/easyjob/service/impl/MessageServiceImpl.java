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
    /**
     * 获取消息列表
     * @param conversationId 会话ID
     * @param lastMessageId 最后一条消息ID
     * @param size 获取数量
     * @return 消息列表
     */
    @Override
    public MessageListVO getMessageList(Long conversationId, Long lastMessageId, Integer size) {
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
        messageListVO.setRecords(messageList);
        messageListVO.setHasMore(messageList.size() > size);
        return messageListVO;
    }
    /**
     * 发送消息
     * @param dto 发送消息参数
     * @return 发送的消息
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public MessageVO sendMessage(MessageSendDTO dto) {
        Long userId = UserContext.getUserId();
        // 1. 验证用户是会话成员
        boolean isMember = conversationMemberService.isMember(dto.getConversationId(), userId);
        if (!isMember) {
            throw new BusinessException("用户不是会话成员");
        }
        // 2. 创建 Message 实体并保存
        Message message = new Message();
        message.setMessageType(dto.getMessageType());
        message.setReplyToMessageId(dto.getReplyToMessageId());
        message.setContent(dto.getContent());
        message.setConversationId(dto.getConversationId());
        message.setSenderId(userId);
        message.setCreateTime(LocalDateTime.now());
        messageMapper.insert(message);
        // 3. 更新会话最后消息：conversationService.updateLastMessage(...)
        conversationService.updateLastMessage(dto.getConversationId(), message.getMessageId(), message.getContent());
        // 4. 增加其他成员未读数：conversationMemberService.incrementUnreadCount(...)
        conversationMemberService.incrementUnreadCount(dto.getConversationId(), userId);
        // 5. 构建并返回 MessageVO
        MessageVO messageVO = new MessageVO();
        messageVO.setMessageId(message.getMessageId().toString());
        messageVO.setConversationId(message.getConversationId().toString());
        messageVO.setSenderId(message.getSenderId().toString());
        messageVO.setMessageType(message.getMessageType());
        messageVO.setContent(message.getContent());
        messageVO.setCreateTime(message.getCreateTime());
        messageVO.setStatus(message.getStatus());
        // websocket推送信息
        Long receiveId = conversationMemberService.getOneReceiveId(dto.getConversationId(), userId);
        if(ChatWebSocketHandler.isOnline(receiveId)){
            Map<String, Object> wsMsg = new HashMap<>();
            wsMsg.put("type", "message");
            wsMsg.put("conversationId", message.getConversationId().toString());
            wsMsg.put("messageId", message.getMessageId().toString());
            wsMsg.put("content", message.getContent());
            wsMsg.put("messageType", message.getMessageType());
            wsMsg.put("senderId", message.getSenderId().toString());
            wsMsg.put("createTime", message.getCreateTime().toString());
            // 直接使用前端传入的头像和昵称，避免数据库查询
            wsMsg.put("senderName", dto.getSenderName());
            wsMsg.put("senderAvatar", dto.getSenderAvatar());
            ChatWebSocketHandler.sendToUser(receiveId, wsMsg);
        }
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
            ChatWebSocketHandler.sendToUser(receiveId, wsMsg);
        }
    }
}
