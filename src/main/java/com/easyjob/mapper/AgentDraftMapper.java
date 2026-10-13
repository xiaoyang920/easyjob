package com.easyjob.mapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.Map;
/** Blog-owned idempotency receipt. Never reads Agent tables. */
@Mapper
public interface AgentDraftMapper {
    int reserve(@Param("runId") String runId,@Param("uid") long uid,@Param("articleId") long articleId,@Param("hash") String hash);
    Map<String,Object> lockReceipt(@Param("runId") String runId);
    Map<String,Object> receipt(@Param("runId") String runId,@Param("uid") long uid);
    int complete(@Param("runId") String runId);
}
