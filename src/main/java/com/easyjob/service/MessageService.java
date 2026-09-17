package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.dto.MessageSendDTO;
import com.easyjob.entity.Message;
import com.easyjob.vo.MessageListVO;
import com.easyjob.vo.MessageVO;

/**
 * 消息Service接口
 */
public interface MessageService extends IService<Message> {
    
    /**
     * 获取会话消息列表
     * @param conversationId 会话ID
     * @param lastMessageId 上一页最后一条消息ID（分页用）
     * @param size 每页数量
     * @return 消息列表
     */
    MessageListVO getMessageList(Long conversationId, Long lastMessageId, Integer size);
    
    /**
     * 发送消息
     * @param dto 发送消息请求
     * @return 消息信息
     */
    MessageVO sendMessage(MessageSendDTO dto);
    
    /**
     * 撤回消息
     * @param messageId 消息ID
     */
    void recallMessage(Long messageId);
}
