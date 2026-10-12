package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Persistence statements only; authorization and transactions belong to the service. */
@Mapper
public interface AdminStatisticsMapper {
    List<Map<String,Object>> configuredLevels();
    List<Map<String,Object>> levelDistribution(@Param("source") String source);
    Long countUnpublished(@Param("source") String source);
    List<Map<String,Object>> articleDistribution(@Param("source") String source);
    Long distinctReaders(@Param("start") java.sql.Date start, @Param("end") java.sql.Date end, @Param("source") String source);
    List<Map<String,Object>> dailyReading(@Param("start") java.sql.Date start, @Param("end") java.sql.Date end, @Param("source") String source);
    List<Map<String,Object>> dailyPublications(@Param("start") java.sql.Timestamp start, @Param("end") java.sql.Timestamp end, @Param("source") String source);
    List<Map<String,Object>> dailyUsers(@Param("start") java.sql.Timestamp start, @Param("end") java.sql.Timestamp end, @Param("source") String source);
}
