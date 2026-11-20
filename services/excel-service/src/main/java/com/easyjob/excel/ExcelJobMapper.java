package com.easyjob.excel;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDate;
import java.util.List;

@Mapper
public interface ExcelJobMapper {
    String probeQueue();
    void enqueue(@Param("jobNo") String jobNo, @Param("ownerId") long ownerId,
                 @Param("requestId") String requestId, @Param("days") int days,
                 @Param("source") String source, @Param("fromDay") LocalDate fromDay,
                 @Param("toDay") LocalDate toDay);
    ExcelJob byRequest(@Param("ownerId") long ownerId, @Param("requestId") String requestId);
    ExcelJob byOwner(@Param("jobNo") String jobNo, @Param("ownerId") long ownerId);
    ExcelJob byLease(@Param("jobNo") String jobNo, @Param("token") String token);
    List<String> candidates(@Param("maxAttempts") int maxAttempts);
    int claim(@Param("jobNo") String jobNo, @Param("token") String token,
              @Param("maxAttempts") int maxAttempts, @Param("leaseSeconds") int leaseSeconds);
    int renew(@Param("jobNo") String jobNo, @Param("token") String token, @Param("leaseSeconds") int leaseSeconds);
    int succeed(@Param("jobNo") String jobNo, @Param("token") String token,
                @Param("fileName") String fileName, @Param("rowCount") int rowCount);
    int fail(@Param("jobNo") String jobNo, @Param("token") String token,
             @Param("state") String state, @Param("error") String error, @Param("delay") int delay);
    List<ExcelJob> exhaustedCandidates(@Param("maxAttempts") int maxAttempts);
    int exhaust(@Param("jobNo") String jobNo, @Param("maxAttempts") int maxAttempts);
}
