package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.AiMessage;
import org.apache.ibatis.annotations.*;

import java.util.List;

@Mapper
public interface AiMessageMapper extends BaseMapper<AiMessage> {
    /**
     * 根据会话id查询消息
     * @param conversationId
     * @return
     */
    default List<AiMessage> selectByConversationId(Long conversationId) {
        return selectList(new LambdaQueryWrapper<AiMessage>()
                .eq(AiMessage::getConversationId, conversationId)
                .orderByAsc(AiMessage::getCreateTime));
    }
}