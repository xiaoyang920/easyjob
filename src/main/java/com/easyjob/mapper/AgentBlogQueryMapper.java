package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.*;

@Mapper
public interface AgentBlogQueryMapper {
    List<Map<String,Object>> published(@Param("ids") List<Long> ids);
    List<Map<String,Object>> userSources(@Param("ids") List<Long> ids);
    List<Map<String,Object>> tags(@Param("names") List<String> names);
    List<Map<String,Object>> categories(@Param("names") List<String> names);
    List<Map<String,Object>> authors(@Param("name") String name);
    List<Map<String,Object>> userArticles(@Param("uid") long uid,@Param("limit") int limit,@Param("offset") int offset);
    List<Map<String,Object>> comments(@Param("aid") long aid,@Param("limit") int limit);
    List<Map<String,Object>> trending(@Param("limit") int limit);
    List<Map<String,Object>> scan(@Param("cursor") long cursor);
    Map<String,Object> article(@Param("id") long id);
    Map<String,Object> lockArticle(@Param("id") long id);
    int activeJobs(@Param("id") long id);
    int repair(@Param("id") long id,@Param("job") String job);
    int repairViews(@Param("id") long id,@Param("count") long count);
    List<Map<String,Object>> jobCounts();
    Long oldestJob();
    int cleanJobs();
    List<String> oldSessions();
    int cleanSessions(@Param("ids") List<String> ids);
    int cleanReads();
}
