package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface RecommendationFeedbackMapper {
    List<Map<String,Object>> findFeedback(@Param("userId") Long userId);
    int deleteFeedback(@Param("userId") Long userId, @Param("articleId") Long articleId);
    int upsertFeedback(@Param("userId") Long userId, @Param("articleId") Long articleId, @Param("authorId") Long authorId, @Param("kind") String kind);
    Long countOtherFeedback(@Param("userId") Long userId, @Param("articleId") Long articleId);
    List<Map<String,Object>> findPublicArticle(@Param("articleId") Long articleId);
    List<Map<String,Object>> lockActiveUser(@Param("userId") Long userId);
}
