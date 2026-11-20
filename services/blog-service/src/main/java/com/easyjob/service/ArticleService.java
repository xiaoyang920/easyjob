package com.easyjob.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.dto.ShareDTO;
import com.easyjob.entity.Article;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.ArticleListVO;
import com.easyjob.vo.PageVO;

import java.util.List;
import java.util.Map;

public interface ArticleService extends IService<Article> {
    Map<String,Object> getUserArticles(Long userId, Integer page, Integer size, String order);

    Long saveArticle(ArticleCreateDTO article);

    ArticleDetailVO getArticleById(Long articleId);
    ArticleDetailVO getEditableArticle(Long articleId);

    void deleteArticle(Long articleId);

    void updateArticle(Long articleId, ArticleCreateDTO article);

    Map<String,Object> getDrafts(Integer page, Integer size);

    void publish(Long articleId);

    /**
     * 获取公开文章列表（支持搜索、分类筛选、排序）
     */
    PageVO listArticles(Integer page, Integer size, String sort, Long categoryId, String keyword);
    PageVO listArticles(Integer page, Integer size, String sort, Long categoryId, String keyword, List<Long> tagIds);
    PageVO listArticles(Integer page, Integer size, String sort, Long categoryId, String keyword, List<Long> tagIds, Long viewerId, boolean readableOnly);

    void increaseViewCount(Long articleId);

    Integer recordArticleShare(ShareDTO shareDTO);

}
