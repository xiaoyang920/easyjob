ALTER TABLE ai_conversation ADD COLUMN is_writing TINYINT NOT NULL DEFAULT 0;
ALTER TABLE ai_conversation ADD COLUMN writing_article_id BIGINT NULL DEFAULT NULL;
CREATE INDEX idx_ai_conv_writing ON ai_conversation (user_id, is_writing, writing_article_id, status, update_time, conversation_id);
