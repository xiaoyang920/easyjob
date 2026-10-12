package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface AdminAgentMetricsMapper {
    List<Map<String,Object>> countStates(@Param("start") java.sql.Timestamp start, @Param("end") java.sql.Timestamp end, @Param("source") String source);
    List<Map<String,Object>> findMetrics(@Param("start") java.sql.Timestamp start, @Param("end") java.sql.Timestamp end, @Param("source") String source);
    List<Map<String,Object>> countDaily(@Param("start") java.sql.Timestamp start, @Param("end") java.sql.Timestamp end, @Param("source") String source);
}
