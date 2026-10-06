CREATE TABLE IF NOT EXISTS agent_background_job (
    job_id CHAR(64) PRIMARY KEY,
    kind VARCHAR(32) NOT NULL,
    user_id BIGINT NOT NULL,
    conversation_id BIGINT NULL,
    payload JSON NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    lease_until DATETIME(6) NULL,
    lease_token CHAR(36) NULL,
    last_error VARCHAR(128) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_background_due (status, available_at),
    KEY idx_background_lease (status, lease_until)
);
CREATE TABLE IF NOT EXISTS article_index_outbox (
    job_id CHAR(36) PRIMARY KEY,
    article_id BIGINT NOT NULL,
    action VARCHAR(16) NOT NULL,
    routing_key VARCHAR(100) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    lease_until DATETIME(6) NULL,
    lease_token CHAR(36) NULL,
    last_error VARCHAR(128) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY idx_article_outbox_due (status, available_at),
    KEY idx_article_outbox_lease (status, lease_until),
    KEY idx_article_outbox_article (article_id)
);
