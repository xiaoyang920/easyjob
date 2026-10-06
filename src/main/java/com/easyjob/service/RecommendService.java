package com.easyjob.service;

import com.easyjob.vo.ArticleListVO;

import java.util.List;

public interface RecommendService {
    List<ArticleListVO> recommend(Long userId,int limit);
    default com.easyjob.vo.PageVO<ArticleListVO> recommendPage(Long userId, int page, int size, Long categoryId, List<Long> tagIds) {
        return recommendPage(userId, page, size, categoryId, tagIds, false);
    }
    com.easyjob.vo.PageVO<ArticleListVO> recommendPage(Long userId, int page, int size, Long categoryId, List<Long> tagIds, boolean readableOnly);
}
