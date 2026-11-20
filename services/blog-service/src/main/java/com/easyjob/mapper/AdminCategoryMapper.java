package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface AdminCategoryMapper {
    int insertCreateAudit(@Param("actorId") Long actorId, @Param("categoryId") long categoryId, @Param("name") String name, @Param("details") String details);
    int insertCategory(@Param("categoryId") long categoryId, @Param("name") String name, @Param("parentId") long parentId, @Param("sortOrder") int sortOrder, @Param("description") String description);
    List<Map<String,Object>> lockParent(@Param("categoryId") long categoryId);
    List<Map<String,Object>> findCategories();
}
