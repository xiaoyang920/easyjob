package com.easyjob.mapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.*;
@Mapper
public interface AdminBlogOperationsMapper {
    int insertReconcileAudit(@Param("actorId") Long actorId,@Param("targetId") Long targetId,@Param("kind") String kind);
    int insertRetryAudit(@Param("actorId") Long actorId,@Param("queue") String queue,@Param("targetId") long targetId,@Param("jobId") String jobId);
    Map<String,Object> viewSummary();
    List<Map<String,Object>> queueSummary(@Param("queue") String queue);
    Long countJobs(@Param("queue") String queue,@Param("state") String state);
    List<Map<String,Object>> findJobs(@Param("queue") String queue,@Param("state") String state,@Param("size") int size,@Param("offset") int offset);
    List<Map<String,Object>> lockJob(@Param("queue") String queue,@Param("jobId") String jobId);
    int retryJob(@Param("queue") String queue,@Param("jobId") String jobId);
}
