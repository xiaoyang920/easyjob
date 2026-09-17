package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.Message;
import com.easyjob.vo.MessageVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * 消息Mapper
 */
@Mapper
public interface MessageMapper extends BaseMapper<Message> {
    
    /**
     * 查询会话消息列表（带发送者信息）
     * @param conversationId 会话ID
     * @param lastMessageId 上一页最后一条消息ID（用于分页，可为null）
     * @param size 每页数量
     * @return 消息列表
     */
    List<MessageVO> selectMessageList(@Param("conversationId") Long conversationId,
                                      @Param("lastMessageId") Long lastMessageId,
                                      @Param("size") Integer size);
}
