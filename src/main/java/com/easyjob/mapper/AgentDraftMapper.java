package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;
import java.util.Map;

/** Persistence statements only; authorization and transactions belong to the service. */
@Mapper
public interface AgentDraftMapper {
    int recordSavedDraft(@Param("articleId") Long articleId, @Param("draftHash") String draftHash, @Param("runId") String runId);
    Map<String,Object> lockRun(@Param("runId") String runId);
    List<Map<String,Object>> lockConversation(@Param("conversationId") Long conversationId);
    List<Map<String,Object>> findRunConversation(@Param("runId") String runId, @Param("userId") long userId);
}
