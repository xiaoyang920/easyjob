package com.easyjob.agent.param;

import lombok.Data;

@Data
public class ResumeParam {
    private String runId;
    private String draftHash;
    
    /**
     * 会话ID
     */
    private Long conversationId;
    
    /**
     * 用户操作：approve / reject / 用户输入的修改意见
     */
    private String action;
}
