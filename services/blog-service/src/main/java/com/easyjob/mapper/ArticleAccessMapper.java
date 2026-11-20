package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ArticleAccessMapper {
    int updateRequiredLevel(@Param("level") Integer level, @Param("articleId") Long articleId);
    List<Map<String,Object>> lockArticle(@Param("articleId") Long articleId);
    List<String> findPermissions(@Param("userId") Long userId);
    List<Map<String,Object>> findAdmin(@Param("userId") Long userId);
}
