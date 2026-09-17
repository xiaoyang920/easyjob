package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.ConversationMember;

/**
 * 会话成员Service接口
 */
public interface ConversationMemberService extends IService<ConversationMember> {
    
    /**
     * 检查用户是否是会话成员
     * @param conversationId 会话ID
     * @param userId 用户ID
     * @return 是否是成员
     */
    boolean isMember(Long conversationId, Long userId);
    
    /**
     * 增加未读数（除发送者外）
     * @param conversationId 会话ID
     * @param excludeUserId 排除的用户ID（发送者）
     */
    void incrementUnreadCount(Long conversationId, Long excludeUserId);
    
    /**
     * 清空未读数
     * @param conversationId 会话ID
     * @param userId 用户ID
     */
    void clearUnreadCount(Long conversationId, Long userId);

    Long getOneReceiveId(Long conversationId, Long excludeUserId);
}
