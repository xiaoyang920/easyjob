package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.easyjob.entity.ArticleTag;
import com.easyjob.vo.TagVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface ArticleTagMapper extends BaseMapper<ArticleTag> {
    
    /**
     * 根据标签名查询标签
     */
    ArticleTag selectByTagName(@Param("tagName") String tagName);
    
    /**
     * 搜索标签（用于联想）
     */
    List<TagVO> searchTags(@Param("keyword") String keyword, @Param("limit") Integer limit);
    
    /**
     * 获取热门标签
     */
    List<TagVO> getHotTags(@Param("limit") Integer limit);
    
    /**
     * 根据文章ID获取标签列表
     */
    List<TagVO> getTagsByArticleId(@Param("articleId") Long articleId);
    
    /**
     * 增加标签使用次数
     */
    void increaseUseCount(@Param("tagId") Long tagId);
    
    /**
     * 减少标签使用次数
     */
    void decreaseUseCount(@Param("tagId") Long tagId);
}
