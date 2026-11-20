package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Database access only. Caller owns business rules and transaction boundaries. */
@Mapper
public interface ArticleIndexOutboxMapper {
    int markCompleted(@Param("jobId") String jobId, @Param("articleId") Long articleId);
    Boolean isCompleted(@Param("jobId") String jobId, @Param("articleId") Long articleId);
    int retryJob(@Param("state") String state, @Param("error") String error, @Param("seconds") int seconds, @Param("jobId") String jobId, @Param("token") String token);
    int markDispatched(@Param("seconds") int seconds, @Param("jobId") String jobId, @Param("token") String token);
    int leaseJob(@Param("token") String token, @Param("jobId") String jobId);
    int exhaustJob(@Param("jobId") String jobId);
    List<Map<String,Object>> lockAvailableJob(@Param("jobId") String jobId);
    List<Map<String,Object>> findCandidates();
    int enqueue(@Param("jobId") String jobId, @Param("articleId") Long articleId, @Param("action") String action, @Param("routingKey") String routingKey);
    List<Map<String,Object>> checkSchema();
}
