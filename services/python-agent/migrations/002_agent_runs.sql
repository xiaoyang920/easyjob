CREATE TABLE IF NOT EXISTS agent_run (
    run_id CHAR(36) PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    request_id CHAR(36) NOT NULL,
    input_hash CHAR(64) NOT NULL,
    execution_token CHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    active_conversation_id BIGINT GENERATED ALWAYS AS
      (CASE WHEN status IN ('running', 'awaiting_approval') THEN conversation_id ELSE NULL END) STORED,
    deadline DATETIME(6) NOT NULL,
    draft_hash CHAR(64) NULL,
    draft_article_id BIGINT NULL,
    result_json JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_agent_active_conversation (active_conversation_id),
    UNIQUE KEY uq_agent_request (user_id, request_id),
    KEY idx_agent_conversation (conversation_id, created_at)
);
CREATE TABLE IF NOT EXISTS agent_run_event (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    node VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    duration_ms BIGINT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_agent_event_run (run_id, event_id)
);
