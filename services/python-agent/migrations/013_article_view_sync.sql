CREATE TABLE IF NOT EXISTS article_view_sync (
    article_id BIGINT NOT NULL PRIMARY KEY,
    target_count INT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    lease_token CHAR(36) NULL,
    lease_until DATETIME(6) NULL,
    last_error VARCHAR(100) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_article_view_sync_ready(available_at,lease_until)
) ENGINE=InnoDB;

INSERT INTO article_view_sync(article_id,target_count,available_at)
SELECT article_id,view_count,TIMESTAMPADD(SECOND,2,UTC_TIMESTAMP(6)) FROM article_info
WHERE status=1 AND deleted=0 AND view_count>0
ON DUPLICATE KEY UPDATE target_count=GREATEST(target_count,VALUES(target_count));
