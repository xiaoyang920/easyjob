package com.easyjob.vo;

import lombok.Data;

/**
 * 操作结果 VO
 * 返回操作后的统计数据
 */
@Data
public class ActionResultVO {
    
    /**
     * 操作是否成功
     */
    private Boolean success;
    
    /**
     * 操作后的状态（true: 已操作，false: 已取消）
     */
    private Boolean status;
    
    /**
     * 操作类型名称
     */
    private String actionTypeName;
    
    /**
     * 文章/评论的最新统计数据
     */
    private Integer count;
    
    /**
     * 提示信息
     */
    private String message;
}
