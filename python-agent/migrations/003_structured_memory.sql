ALTER TABLE user_memory ADD COLUMN memory_type VARCHAR(16) NOT NULL DEFAULT 'event';
ALTER TABLE user_memory ADD COLUMN scope VARCHAR(16) NOT NULL DEFAULT 'user';
ALTER TABLE user_memory ADD COLUMN scope_conversation_id BIGINT NULL;
ALTER TABLE user_memory ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE user_memory ADD COLUMN memory_key VARCHAR(64) NULL;
ALTER TABLE user_memory ADD COLUMN source_quote VARCHAR(1000) NULL;
CREATE TABLE IF NOT EXISTS user_memory_change (
    run_id CHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    conversation_id BIGINT NOT NULL,
    change_hash CHAR(64) NOT NULL,
    result_json JSON NOT NULL,
    index_synced TINYINT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
