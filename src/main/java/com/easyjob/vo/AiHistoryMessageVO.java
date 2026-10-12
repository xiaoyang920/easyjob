package com.easyjob.vo;

import com.easyjob.entity.AiMessage;
import lombok.Data;
import lombok.EqualsAndHashCode;
import java.util.List;
import java.util.Map;

/** Conversation history also contains durable run outcomes, not just saved replies. */
@Data
@EqualsAndHashCode(callSuper = true)
public class AiHistoryMessageVO extends AiMessage {
    private String runId;
    private String runStatus;
    private String runStartedAt;
    private String runFinishedAt;
    private Boolean recoverable;
    private List<Map<String, Object>> agentEvents;
}
