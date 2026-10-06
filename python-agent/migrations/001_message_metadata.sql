ALTER TABLE ai_message ADD COLUMN draft_article_id BIGINT NULL;
ALTER TABLE ai_message ADD COLUMN citations JSON NULL;
