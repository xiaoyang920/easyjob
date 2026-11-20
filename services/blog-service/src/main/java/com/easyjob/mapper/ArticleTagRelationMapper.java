package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.ArticleTagRelation;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface ArticleTagRelationMapper extends BaseMapper<ArticleTagRelation> {
    
    /**
     * 根据文章ID删除所有关联
     */
    void deleteByArticleId(@Param("articleId") Long articleId);
    
    /**
     * 批量插入文章-标签关联
     */
    void batchInsert(@Param("relations") List<ArticleTagRelation> relations);
    
    /**
     * 根据文章ID获取关联的标签ID列表
     */
    List<Long> getTagIdsByArticleId(@Param("articleId") Long articleId);
}
