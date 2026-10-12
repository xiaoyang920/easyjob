package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ArticleSearchMapper {
    List<Map<String,Object>> findCurrentArticles(@Param("ids") List<Long> ids);
}
