ALTER TABLE article_revision ADD COLUMN lock_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE article_revision ADD COLUMN updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3);
ALTER TABLE article_revision ADD COLUMN deleted TINYINT NOT NULL DEFAULT 0;
ALTER TABLE article_revision ADD COLUMN is_current TINYINT NOT NULL DEFAULT 0;
ALTER TABLE article_revision ADD COLUMN data_source VARCHAR(16) NOT NULL DEFAULT 'business';
ALTER TABLE article_revision ADD COLUMN required_level INT NOT NULL DEFAULT 0;
ALTER TABLE article_revision ADD COLUMN current_article_id BIGINT GENERATED ALWAYS AS (CASE WHEN is_current=1 AND deleted=0 THEN article_id ELSE NULL END) STORED;
CREATE UNIQUE INDEX uk_revision_current ON article_revision(current_article_id);
CREATE INDEX ix_revision_workspace ON article_revision(author_id,deleted,is_current,state,updated_at);
