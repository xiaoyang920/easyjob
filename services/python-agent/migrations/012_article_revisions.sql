ALTER TABLE article_info ADD COLUMN latest_revision_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE article_info ADD COLUMN published_revision_id BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS article_revision (
 revision_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 article_id BIGINT NOT NULL,
 version_no INT NOT NULL,
 author_id BIGINT NOT NULL,
 base_revision_id BIGINT NOT NULL DEFAULT 0,
 state TINYINT NOT NULL,
 payload JSON NOT NULL,
 content_hash CHAR(64) NOT NULL,
 review_reason VARCHAR(1000) NOT NULL DEFAULT '',
 reviewer_id BIGINT NULL,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 submitted_at DATETIME(3) NULL,
 reviewed_at DATETIME(3) NULL,
 active_article_id BIGINT GENERATED ALWAYS AS (CASE WHEN state=1 THEN article_id ELSE NULL END) STORED,
 UNIQUE KEY uk_article_version(article_id,version_no),
 UNIQUE KEY uk_pending_article(active_article_id),
 KEY ix_review_queue(state,submitted_at,revision_id),
 KEY ix_author_revision(author_id,created_at)
);
CREATE TABLE IF NOT EXISTS article_review_log (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 article_id BIGINT NOT NULL,
 revision_id BIGINT NOT NULL,
 actor_id BIGINT NOT NULL,
 action VARCHAR(24) NOT NULL,
 reason VARCHAR(1000) NOT NULL DEFAULT '',
 content_hash CHAR(64) NOT NULL,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 KEY ix_article_review(article_id,id),
 KEY ix_revision_review(revision_id,id)
);
