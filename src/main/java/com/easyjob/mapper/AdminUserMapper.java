package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface AdminUserMapper {
    List<Long> findArticleIds(@Param("userId") Long userId);
    int insertAudit(@Param("actorId") Long actorId, @Param("userId") Long userId, @Param("beforeValue") String beforeValue, @Param("afterValue") String afterValue, @Param("reason") String reason, @Param("details") String details);
    int updateProfile(@Param("nickName") String nickName, @Param("introduction") String introduction, @Param("role") Integer role, @Param("status") Integer status, @Param("authIncrement") int authIncrement, @Param("userId") Long userId);
    int correctProgress(@Param("millis") long millis, @Param("level") int level, @Param("userId") Long userId);
    Map<String,Object> lockProgress(@Param("userId") Long userId);
    int ensureProgress(@Param("userId") Long userId);
    List<Map<String,Object>> lockActorAndUser(@Param("actorId") Long actorId, @Param("userId") Long userId);
    List<Map<String,Object>> findProgress(@Param("userId") Long userId);
    List<Map<String,Object>> findProfile(@Param("userId") Long userId);
}
