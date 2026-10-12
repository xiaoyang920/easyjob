package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Persistence statements only; authorization and transactions belong to the service. */
@Mapper
public interface AdminConsoleMapper {
    int updateArticleVisibility(@Param("status") Integer status, @Param("articleId") Long articleId);
    int insertArticleAudit(@Param("actorId") Long actorId, @Param("action") String action, @Param("articleId") Long articleId, @Param("beforeValue") String beforeValue, @Param("afterValue") String afterValue);
    List<Map<String,Object>> lockArticle(@Param("articleId") Long articleId);
    List<Map<String,Object>> lockOwner(@Param("userId") Long userId);
    List<Map<String,Object>> findArticleOwner(@Param("articleId") Long articleId);
    List<Map<String,Object>> findOperationLogs(@Param("size") int size, @Param("offset") int offset);
    Long countOperationLogs();
    Long countPendingReviews();
    Long totalReadingSeconds();
    Long countRemoved();
    Long countRestricted();
    Long countPublished();
    Long countUsers();
    Map<String,Object> findOperator(@Param("userId") Long userId);
    Long countArticles(@Param("pattern") String pattern, @Param("status") Integer status);
    List<Map<String,Object>> findArticles(@Param("pattern") String pattern, @Param("status") Integer status, @Param("size") int size, @Param("offset") int offset);
    Long countMatchingUsers(@Param("pattern") String pattern);
    List<Map<String,Object>> findUsers(@Param("pattern") String pattern, @Param("size") int size, @Param("offset") int offset);
}
