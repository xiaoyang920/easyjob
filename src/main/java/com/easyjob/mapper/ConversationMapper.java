package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.Conversation;
import com.easyjob.vo.ConversationVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * 会话Mapper
 */
@Mapper
public interface ConversationMapper extends BaseMapper<Conversation> {
    Long lockConversation(@Param("id") Long id);
    
    /**
     * 查询用户的会话列表
     * @param userId 当前用户ID
     * @return 会话列表
     */
    List<ConversationVO> selectConversationList(@Param("userId") Long userId);
    
    /**
     * 查询两个用户之间是否存在单聊会话
     * @param userId1 用户1
     * @param userId2 用户2
     * @return 会话ID，不存在则返回null
     */
    Long selectExistConversation(@Param("userId1") Long userId1, @Param("userId2") Long userId2);

    Integer selectUnreadCount(@Param("conversationId") Long conversationId, @Param("userId") Long userId);

    Long getLastMessageId(@Param("conversationId") Long conversationId);

    void updateLastMessage(@Param("conversationId") Long conversationId, @Param("messageId") Long messageId, @Param("content") String content);
}
