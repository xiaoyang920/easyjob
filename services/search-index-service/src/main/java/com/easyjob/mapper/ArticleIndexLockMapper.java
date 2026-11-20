package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface ArticleIndexLockMapper {
    Integer acquire(@Param("name") String name);
    Integer release(@Param("name") String name);
}
