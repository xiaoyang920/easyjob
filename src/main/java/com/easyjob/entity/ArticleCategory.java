package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文章分类实体类
 */
@Data
@TableName("article_category")
public class ArticleCategory {
    
    /**
     * 分类ID
     */
    @TableId(value = "category_id", type = IdType.ASSIGN_ID)
    private Long categoryId;
    
    /**
     * 分类名称
     */
    @TableField("category_name")
    private String categoryName;
    
    /**
     * 父分类ID（0表示顶级分类）
     */
    @TableField("parent_id")
    private Long parentId;
    
    /**
     * 排序值（越小越靠前）
     */
    @TableField("sort_order")
    private Integer sortOrder;
    
    /**
     * 分类描述
     */
    @TableField("description")
    private String description;
    
    /**
     * 该分类下的文章数量
     */
    @TableField("article_count")
    private Integer articleCount;
    
    /**
     * 状态（1-启用，0-禁用）
     */
    @TableField("status")
    private Integer status;
    
    /**
     * 创建时间
     */
    @TableField("create_time")
    private LocalDateTime createTime;
    
    /**
     * 更新时间
     */
    @TableField("update_time")
    private LocalDateTime updateTime;
}
