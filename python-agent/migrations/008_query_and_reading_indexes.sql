CREATE TABLE IF NOT EXISTS article_read_receipt (
    article_id BIGINT NOT NULL,
    reader_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    read_day DATE NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY(article_id,reader_hash,read_day),
    KEY idx_read_receipt_day(read_day)
);
CREATE INDEX idx_agent_created ON agent_run(created_at,run_id);
CREATE INDEX idx_agent_expiry ON agent_run(status,deadline);
CREATE INDEX idx_agent_terminal_retention ON agent_run(status,updated_at);
CREATE INDEX idx_article_feed ON article_info(status,deleted,publish_time,article_id);
CREATE INDEX idx_article_category_feed ON article_info(status,deleted,category_id,publish_time,article_id);
CREATE INDEX idx_user_action_read ON user_action(user_id,article_id,action_type,action_time);
CREATE INDEX idx_user_action_recent ON user_action(user_id,action_time,article_id,action_type);
