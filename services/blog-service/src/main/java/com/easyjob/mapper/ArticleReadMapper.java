package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ArticleReadMapper {
    int touchHistory(@Param("authorId") long authorId, @Param("actionId") Long actionId);
    int insertHistory(@Param("userId") Long userId, @Param("articleId") Long articleId, @Param("authorId") long authorId);
    List<Map<String,Object>> findHistory(@Param("userId") Long userId, @Param("articleId") Long articleId);
    int incrementViews(@Param("articleId") Long articleId);
    int insertReceipt(@Param("articleId") Long articleId, @Param("readerHash") String readerHash, @Param("day") java.time.LocalDate day);
    List<Map<String,Object>> lockArticle(@Param("articleId") Long articleId);
}
