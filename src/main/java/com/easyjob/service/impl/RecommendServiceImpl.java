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
    /**
     * 推荐文章
     * @param userId
     * @param limit
     * @return
     */
    @Override
    public List<ArticleListVO> recommend(Long userId, int limit) {
        //1.获取用户偏好的标签
        List<Long> topTagIds = userTagPreferenceMapper.selectTopTagIds(userId, 10);

        if(topTagIds==null||topTagIds.isEmpty()){
            //没有偏好数据，返回热门文章
            log.info("用户{}没有偏好数据，返回热门文章",userId);
            return articleMapper.selectHotArticles(limit);
        }
        //2.根据偏好标签推荐文章(排除已浏览的)
        List<ArticleListVO> articles = articleMapper.selectRecommendArticles(userId, topTagIds, limit);
        //3.如果推荐结果不足，用热门文章补充
        if(articles.size()<limit){
            log.info("用户{}推荐文章不足，返回热门文章",userId);
            List<Long> existIds = new ArrayList<>();
            existIds = articles.stream().map(ArticleListVO::getArticleId).map(Long::parseLong).toList();
            List<ArticleListVO> hotArticles = articleMapper.selectHotArticlesExclude(
                    existIds, limit - articles.size()
            );
            articles.addAll(hotArticles);
        }
        return articles;
    }
}
