package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.ConversationMember;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 会话成员Mapper
 */
@Mapper
public interface ConversationMemberMapper extends BaseMapper<ConversationMember> {
    
    /**
     * 增加未读数（除了发送者之外的所有成员）
     * @param conversationId 会话ID
     * @param excludeUserId 排除的用户ID（发送者）
     * @return 影响行数
     */
    int incrementUnreadCount(@Param("conversationId") Long conversationId, 
                             @Param("excludeUserId") Long excludeUserId);
    
    /**
     * 清空用户在某会话的未读数
     * @param conversationId 会话ID
     * @param userId 用户ID
     * @return 影响行数
     */
    int clearUnreadCount(@Param("conversationId") Long conversationId, 
                         @Param("userId") Long userId);

    Boolean isMember(Long conversationId, Long userId);

    Integer selectTotalUnreadCount(Long userId);

    void updateIsDeleted(Long conversationId, Long userId);

    Long selectOneReceiveId(@Param("conversationId") Long conversationId, @Param("userId") Long userId);
}
