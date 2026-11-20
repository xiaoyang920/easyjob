ALTER TABLE article_info ADD COLUMN required_level INT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS reading_level_rule (
 level INT NOT NULL PRIMARY KEY,
 min_seconds BIGINT NOT NULL,
 UNIQUE KEY uq_reading_threshold(min_seconds)
);
INSERT IGNORE INTO reading_level_rule(level,min_seconds) VALUES (0,0),(1,3600),(2,18000),(3,72000),(4,180000);
CREATE TABLE IF NOT EXISTS user_reading_progress (
 user_id BIGINT NOT NULL PRIMARY KEY,
 total_millis BIGINT NOT NULL DEFAULT 0,
 earned_level INT NOT NULL DEFAULT 0,
 active_session CHAR(36) NULL,
 updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
);
CREATE TABLE IF NOT EXISTS reading_session (
 session_id CHAR(36) NOT NULL PRIMARY KEY,
 user_id BIGINT NOT NULL,
 article_id BIGINT NOT NULL,
 last_sequence BIGINT NOT NULL DEFAULT 0,
 last_heartbeat DATETIME(3) NOT NULL,
 active TINYINT NOT NULL DEFAULT 1,
 credited_millis BIGINT NOT NULL DEFAULT 0,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 INDEX ix_reading_owner(user_id,created_at)
);
CREATE TABLE IF NOT EXISTS user_reading_daily (
 user_id BIGINT NOT NULL,
 read_day DATE NOT NULL,
 total_millis BIGINT NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,read_day)
);
