ALTER TABLE ai_conversation ADD COLUMN origin_article_id BIGINT NULL DEFAULT NULL;
CREATE INDEX idx_ai_conv_origin ON ai_conversation (user_id, origin_article_id, status, update_time, conversation_id);
