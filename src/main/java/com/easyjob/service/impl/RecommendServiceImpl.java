package com.easyjob.service.impl;

import com.easyjob.mapper.ArticleMapper;
import com.easyjob.mapper.UserTagPreferenceMapper;
import com.easyjob.service.RecommendService;
import com.easyjob.vo.ArticleListVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
@Slf4j
@Service
public class RecommendServiceImpl implements RecommendService {
    @Autowired
    private UserTagPreferenceMapper userTagPreferenceMapper;
    @Autowired
    private ArticleMapper articleMapper;
    @Autowired private com.easyjob.service.ArticlePreferenceService profile;
    @Autowired private com.easyjob.service.ArticleAccessService access;
    /**
     * 推荐文章
     * @param userId
     * @param limit
     * @return
     */
    @Override
    public List<ArticleListVO> recommend(Long userId, int limit) {
        return recommendPage(userId, 1, limit, null, List.of()).getRecords();
    }

    @Override
    public com.easyjob.vo.PageVO<ArticleListVO> recommendPage(Long userId, int page, int size, Long categoryId, List<Long> tagIds, boolean readableOnly) {
        page = Math.max(1, Math.min(1000, page));
        size = Math.max(1, Math.min(50, size));
        List<Long> tags = tagIds == null ? List.of() : tagIds.stream().filter(id -> id != null && id > 0).distinct().limit(8).toList();
        List<Long> interests = userId == null ? List.of() : userTagPreferenceMapper.selectTopTagIds(userId, 8);
        if (interests == null) interests = List.of();
        var reader = access.reader(userId);
        var topics = profile.topics(userId);
        var result = articleMapper.listRecommendedArticles(new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(page, size),
                userId, interests, categoryId, tags, topics, topics.stream().map(com.easyjob.service.ArticlePreferenceService::titlePattern).toList(), reader.level(), reader.admin(), readableOnly);
        result.setRecords(com.easyjob.service.RecommendationDiversity.reorder(result.getRecords()));
        return com.easyjob.vo.PageVO.fromIPage(result);
    }
}
