package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ReadingGrowthMapper {
    int creditDay(@Param("userId") Long userId, @Param("day") java.time.LocalDate day, @Param("millis") long millis, @Param("increment") long increment);
    int updateProgress(@Param("millis") long millis, @Param("level") int level, @Param("now") java.sql.Timestamp now, @Param("userId") Long userId);
    int heartbeatSession(@Param("sequence") long sequence, @Param("now") java.sql.Timestamp now, @Param("active") boolean active, @Param("credit") long credit, @Param("sessionId") String sessionId);
    int activateSession(@Param("sessionId") String sessionId, @Param("level") int level, @Param("now") java.sql.Timestamp now, @Param("userId") Long userId);
    int insertSession(@Param("sessionId") String sessionId, @Param("userId") Long userId, @Param("articleId") Long articleId, @Param("now") java.sql.Timestamp now, @Param("active") boolean active);
    List<Map<String,Object>> findReadableArticle(@Param("articleId") Long articleId);
    Map<String,Object> lockProgress(@Param("userId") Long userId);
    int ensureProgress(@Param("userId") Long userId);
    int promoteEarnedLevel(@Param("level") int level, @Param("userId") Long userId, @Param("millis") long millis, @Param("earned") int earned);
    List<Map<String,Object>> findProgress(@Param("userId") Long userId);
    List<Map<String,Object>> findRules();
    List<Map<String,Object>> findSession(@Param("sessionId") String sessionId, @Param("userId") Long userId);
}
