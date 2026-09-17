package com.easyjob.vo;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 消息列表VO（带分页信息）
 */
@Data
@NoArgsConstructor
public class MessageListVO {
    
    /**
     * 消息列表
     */
    private List<MessageVO> records;
    
    /**
     * 是否还有更多历史消息
     */
    private Boolean hasMore;
}
