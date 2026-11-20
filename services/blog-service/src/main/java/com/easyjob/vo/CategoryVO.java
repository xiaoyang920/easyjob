package com.easyjob.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.util.List;

/**
 * 文章分类VO
 * 用于返回给前端的分类信息
 */
@Data
public class CategoryVO {
    
    /**
     * 分类ID
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long categoryId;
    
    /**
     * 分类名称
     */
    private String categoryName;
    
    /**
     * 父分类ID（0表示顶级分类）
     */
    @JsonSerialize(using = ToStringSerializer.class)
    private Long parentId;
    
    /**
     * 排序值
     */
    private Integer sortOrder;
    
    /**
     * 分类描述
     */
    private String description;
    
    /**
     * 该分类下的文章数量
     */
    private Integer articleCount;
    
    /**
     * 状态（1-启用，0-禁用）
     */
    private Integer status;
    
    /**
     * 创建时间（格式化字符串）
     */
    private String createTime;
    
    /**
     * 子分类列表（用于树形结构）
     */
    private List<CategoryVO> children;
}
