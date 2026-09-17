package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文章标签实体类
 */
@Data
@TableName("article_tag")
public class ArticleTag {
    
    /**
     * 标签ID
     */
    @TableId(value = "tag_id", type = IdType.AUTO)
    private Long tagId;
    
    /**
     * 标签名称
     */
    @TableField("tag_name")
    private String tagName;
    
    /**
     * 使用次数（关联文章数量）
     */
    @TableField("use_count")
    private Integer useCount;
    
    /**
     * 创建时间
     */
    @TableField("create_time")
    private LocalDateTime createTime;
}
