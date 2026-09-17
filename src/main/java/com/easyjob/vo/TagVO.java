package com.easyjob.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

/**
 * 文章标签VO
 * 用于返回给前端的标签信息
 */
@Data
public class TagVO {
    
    /**
     * 标签ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long tagId;
    
    /**
     * 标签名称
     */
    private String tagName;
    
    /**
     * 使用次数（关联文章数量）
     */
    private Integer useCount;
}
