ALTER TABLE ai_conversation ADD COLUMN is_pinned TINYINT NOT NULL DEFAULT 0;
ALTER TABLE ai_conversation ADD COLUMN metadata_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE ai_message ADD COLUMN run_id CHAR(36) NULL;
CREATE INDEX ix_conversation_library ON ai_conversation(user_id,status,is_pinned,update_time,conversation_id);
CREATE TABLE IF NOT EXISTS agent_answer_feedback (
  run_id CHAR(36) NOT NULL,
  user_id BIGINT NOT NULL,
  rating VARCHAR(16) NOT NULL,
  reason VARCHAR(24) NOT NULL DEFAULT '',
  comment VARCHAR(500) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY(run_id,user_id),
  KEY ix_feedback_rating(rating,updated_at)
);
