package com.easyjob.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.component.RedisComponent;
import com.easyjob.entity.ArticleTag;
import com.easyjob.entity.ArticleTagRelation;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleTagMapper;
import com.easyjob.mapper.ArticleTagRelationMapper;
import com.easyjob.service.ArticleTagService;
import com.easyjob.vo.TagVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Service
public class ArticleTagServiceImpl extends ServiceImpl<ArticleTagMapper, ArticleTag> implements ArticleTagService {
    
    @Autowired
    private ArticleTagMapper articleTagMapper;
    
    @Autowired
    private ArticleTagRelationMapper articleTagRelationMapper;
    @Autowired
    private RedisComponent redisComponent;
    /**
     * 搜索标签（用于联想）
     */
    @Override
    public List<TagVO> searchTags(String keyword, Integer limit) {
        if (keyword == null || keyword.trim().isEmpty()) {
            return new ArrayList<>();
        }
        if (limit == null || limit <= 0) {
            limit = 10;
        }
        return articleTagMapper.searchTags(keyword.trim(), limit);
    }
    
    @Override
    public List<TagVO> getHotTags(Integer limit) {
        if (limit == null || limit <= 0) {
            limit = 10;
        }
        //先从Redis缓存中获取
        List<TagVO> hotTags = redisComponent.getHotTags();
        if (hotTags != null && !hotTags.isEmpty()) {
            return hotTags;
        }
        hotTags = articleTagMapper.getHotTags(limit);
        redisComponent.saveHotTags(hotTags);
        return hotTags;
    }
    
    @Override
    public List<TagVO> getTagsByArticleId(Long articleId) {
        if (articleId == null) {
            return new ArrayList<>();
        }
        return articleTagMapper.getTagsByArticleId(articleId);
    }
    
    /**
     * 处理文章标签
     * 1. 先删除旧的关联关系（并减少旧标签的使用次数）
     * 2. 创建不存在的标签
     * 3. 建立新的关联关系（并增加新标签的使用次数）
     */
    @Override
    @Transactional
    public void handleArticleTags(Long articleId, List<String> tagNames) {
        if (articleId == null) {
            throw new BusinessException("文章ID不能为空");
        }
        
        // 1. 获取旧的标签ID列表，减少使用次数
        List<Long> oldTagIds = articleTagRelationMapper.getTagIdsByArticleId(articleId);
        if (oldTagIds != null && !oldTagIds.isEmpty()) {
            for (Long tagId : oldTagIds) {
                articleTagMapper.decreaseUseCount(tagId);
            }
        }
        
        // 2. 删除旧的关联关系
        articleTagRelationMapper.deleteByArticleId(articleId);
        
        // 3. 如果没有新标签，直接返回
        if (tagNames == null || tagNames.isEmpty()) {
            return;
        }
        
        // 4. 处理新标签
        List<ArticleTagRelation> relations = new ArrayList<>();
        LocalDateTime now = LocalDateTime.now();
        
        for (String tagName : tagNames) {
            if (tagName == null || tagName.trim().isEmpty()) {
                continue;
            }
            
            String trimmedTagName = tagName.trim();
            
            // 4.1 查询标签是否存在
            ArticleTag tag = articleTagMapper.selectByTagName(trimmedTagName);
            
            // 4.2 不存在则创建
            if (tag == null) {
                tag = new ArticleTag();
                tag.setTagName(trimmedTagName);
                tag.setUseCount(0);
                tag.setCreateTime(now);
                articleTagMapper.insert(tag);
            }
            
            // 4.3 增加使用次数
            articleTagMapper.increaseUseCount(tag.getTagId());
            
            // 4.4 准备关联关系
            ArticleTagRelation relation = new ArticleTagRelation();
            relation.setArticleId(articleId);
            relation.setTagId(tag.getTagId());
            relation.setCreateTime(now);
            relations.add(relation);
        }
        
        // 5. 批量插入关联关系
        if (!relations.isEmpty()) {
            articleTagRelationMapper.batchInsert(relations);
        }
    }
    
    /**
     * 删除文章的所有标签关联
     * 同时减少相关标签的使用次数
     */
    @Override
    @Transactional
    public void removeArticleTags(Long articleId) {
        if (articleId == null) {
            return;
        }
        
        // 1. 获取标签ID列表，减少使用次数
        List<Long> tagIds = articleTagRelationMapper.getTagIdsByArticleId(articleId);
        if (tagIds != null && !tagIds.isEmpty()) {
            for (Long tagId : tagIds) {
                articleTagMapper.decreaseUseCount(tagId);
            }
        }
        
        // 2. 删除关联关系
        articleTagRelationMapper.deleteByArticleId(articleId);
    }
}
