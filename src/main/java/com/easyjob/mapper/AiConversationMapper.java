package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.AiConversation;
import org.apache.ibatis.annotations.*;

import java.time.LocalDateTime;
import java.util.List;

@Mapper
public interface AiConversationMapper extends BaseMapper<AiConversation> {

    List<AiConversation> selectByUserId(@Param("userId") Long userId, @Param("limit") int limit);

    void incrementMessageCount(@Param("conversationId") Long conversationId);
    
    void updateTitle(@Param("conversationId") Long conversationId, @Param("title") String title);

    List<AiConversation> selectByUserIdWithCursor(@Param("userId") Long userId,
                                                  @Param("lastUpdateTime") LocalDateTime lastUpdateTime,
                                                  @Param("lastId") Long lastId,
                                                  @Param("limit") int limit);
}