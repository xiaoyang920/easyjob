package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;

import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Fixed statements with bound parameters; locking reads bypass MyBatis caches. */
@Mapper
public interface AgentRunMapper {
    List<Map<String, Object>> findRun(@Param("runId") String runId, @Param("uid") long uid);
    List<Map<String, Object>> findExecutingRun(@Param("runId") String runId, @Param("uid") long uid, @Param("token") String token);
}
