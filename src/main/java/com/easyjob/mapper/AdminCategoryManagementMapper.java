package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface AdminCategoryManagementMapper {
    int incrementVersion(@Param("categoryId") Long categoryId);
    int redirectCategory(@Param("targetId") Long targetId, @Param("categoryId") long categoryId);
    int moveArticle(@Param("targetId") Long targetId, @Param("articleId") long articleId);
    List<Map<String,Object>> lockArticlesForMove(@Param("categoryId") long categoryId);
    List<Long> findArticleIds(@Param("categoryId") long categoryId);
    int updateCategory(@Param("name") String name, @Param("sortOrder") Integer sortOrder, @Param("description") String description, @Param("status") Integer status, @Param("categoryId") long categoryId);
    int insertAudit(@Param("actorId") Long actorId, @Param("action") String action, @Param("categoryId") long categoryId, @Param("beforeValue") String beforeValue, @Param("afterValue") String afterValue, @Param("details") String details);
    List<Map<String,Object>> lockEnabledChildren(@Param("parentId") long parentId);
    List<Map<String,Object>> lockIdentity(@Param("categoryId") long categoryId);
    List<Map<String,Object>> findParent(@Param("categoryId") long categoryId);
    List<Map<String,Object>> lockCategory(@Param("categoryId") long categoryId);
}
