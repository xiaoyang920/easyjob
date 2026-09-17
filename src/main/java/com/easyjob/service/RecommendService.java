package com.easyjob.service;

import com.easyjob.vo.ArticleListVO;

import java.util.List;

public interface RecommendService {
    List<ArticleListVO> recommend(Long userId,int limit);
}
