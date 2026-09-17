package com.easyjob.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文章标签关联实体类
 */
@Data
@TableName("article_tag_relation")
public class ArticleTagRelation {
    
    /**
     * 关联ID
     */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    
    /**
     * 文章ID
     */
    @TableField("article_id")
    private Long articleId;
    
    /**
     * 标签ID
     */
    @TableField("tag_id")
    private Long tagId;
    
    /**
     * 创建时间
     */
    @TableField("create_time")
    private LocalDateTime createTime;
}
