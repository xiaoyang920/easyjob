package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.AiConversation;
import org.apache.ibatis.annotations.*;

import java.time.LocalDateTime;
import java.util.List;

@Mapper
public interface AiConversationMapper extends BaseMapper<AiConversation> {

    @Select("SELECT * FROM ai_conversation WHERE user_id = #{userId} AND status = 1 ORDER BY update_time DESC LIMIT #{limit}")
    List<AiConversation> selectByUserId(@Param("userId") Long userId, @Param("limit") int limit);

    @Update("UPDATE ai_conversation SET message_count = message_count + 1, update_time = NOW() WHERE conversation_id = #{conversationId}")
    void incrementMessageCount(@Param("conversationId") Long conversationId);
    
    @Update("UPDATE ai_conversation SET title = #{title} WHERE conversation_id = #{conversationId}")
    void updateTitle(@Param("conversationId") Long conversationId, @Param("title") String title);

    List<AiConversation> selectByUserIdWithCursor(@Param("userId") Long userId,
                                                  @Param("lastUpdateTime") LocalDateTime lastUpdateTime,
                                                  @Param("lastId") Long lastId,
                                                  @Param("limit") int limit);
}