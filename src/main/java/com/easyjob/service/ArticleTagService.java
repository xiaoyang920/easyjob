package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.entity.ArticleTag;
import com.easyjob.vo.TagVO;

import java.util.List;

public interface ArticleTagService extends IService<ArticleTag> {
    
    /**
     * 搜索标签（用于联想）
     */
    List<TagVO> searchTags(String keyword, Integer limit);
    
    /**
     * 获取热门标签
     */
    List<TagVO> getHotTags(Integer limit);
    
    /**
     * 根据文章ID获取标签列表
     */
    List<TagVO> getTagsByArticleId(Long articleId);
    
    /**
     * 处理文章标签（保存/更新文章时调用）
     * 自动创建不存在的标签，建立关联关系
     * @param articleId 文章ID
     * @param tagNames 标签名列表
     */
    void handleArticleTags(Long articleId, List<String> tagNames);
    
    /**
     * 删除文章的所有标签关联（删除文章时调用）
     * @param articleId 文章ID
     */
    void removeArticleTags(Long articleId);
}
