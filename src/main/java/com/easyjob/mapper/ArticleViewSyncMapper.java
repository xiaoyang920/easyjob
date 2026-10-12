package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ArticleViewSyncMapper {
    List<Map<String,Object>> findArticleVisibility(@Param("articleId") long articleId);
    int retryJob(@Param("error") String error, @Param("seconds") int seconds, @Param("articleId") long articleId, @Param("token") String token);
    int releaseNewerTarget(@Param("articleId") long articleId, @Param("token") String token);
    int completeJob(@Param("articleId") long articleId, @Param("token") String token, @Param("count") int count);
    int leaseJob(@Param("token") String token, @Param("articleId") long articleId);
    List<Map<String,Object>> lockAvailableJob();
    int enqueue(@Param("articleId") long articleId, @Param("targetCount") int targetCount);
    List<Map<String,Object>> checkSchema();
}
