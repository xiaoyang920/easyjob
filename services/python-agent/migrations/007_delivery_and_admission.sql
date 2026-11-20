CREATE TABLE IF NOT EXISTS agent_execution_gate (
    gate_id INT PRIMARY KEY
);
INSERT IGNORE INTO agent_execution_gate (gate_id) VALUES (1);
CREATE TABLE IF NOT EXISTS agent_execution_lease (
    ticket CHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    state VARCHAR(12) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_execution_expiry (expires_at),
    KEY idx_execution_user (user_id,state)
);
CREATE TABLE IF NOT EXISTS agent_stream_frame (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    execution_token CHAR(36) NOT NULL,
    data MEDIUMTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_stream_run (run_id,execution_token,event_id),
    KEY idx_stream_created (created_at)
);
ALTER TABLE message ADD COLUMN client_message_id VARCHAR(64) NULL;
CREATE UNIQUE INDEX uq_message_client ON message (sender_id,client_message_id);
