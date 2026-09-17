package com.easyjob.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.easyjob.entity.Article;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.vo.ArticleListVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Collection;
import java.util.List;


@Mapper
public interface ArticleMapper extends BaseMapper<Article> {

    ArticleDetailVO selectArticleAndUser(Long articleId);

    /**
     * 获取公开文章列表（支持分页、搜索、排序）
     */
    IPage<ArticleListVO> listArticles(Page<ArticleListVO> page, 
                                      @Param("sort") String sort, 
                                      @Param("categoryId") Long categoryId, 
                                      @Param("keyword") String keyword);

    void changeLikeCount(Long articleId,@Param("count") int i);

    void changeCollectCount(Long articleId,@Param("count") int i);

    IPage<ArticleListVO> listUserCollectionOrLike(Page<ArticleListVO> pageParam, 
                                                   @Param("userId") Long userId,
                                                   @Param("type") Integer type,
                                                   @Param("order") String order);

    void changeViewCount(@Param("articleId") Long articleId,@Param("count") int i);

    void changeCommentCount(@Param("articleId") Long articleId,@Param("count") int i);

    void changeShareCount(@Param("articleId") Long articleId,@Param("count") int count);

    Integer getShareCount(Long articleId);

    List<ArticleDetailVO> selectArticlesAndUsers(List<String> articleIds);

    List<ArticleListVO> selectHotArticles(int limit);

    List<ArticleListVO> selectRecommendArticles(Long userId, List<Long> topTagIds, int limit);

    List<ArticleListVO> selectHotArticlesExclude(List<Long> existIds, int i);
}
