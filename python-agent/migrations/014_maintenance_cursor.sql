CREATE TABLE IF NOT EXISTS maintenance_cursor (
 kind VARCHAR(32) NOT NULL PRIMARY KEY,
 last_id BIGINT NOT NULL DEFAULT 0,
 last_key VARCHAR(32) NULL,
 scanned BIGINT NOT NULL DEFAULT 0,
 repaired BIGINT NOT NULL DEFAULT 0,
 next_at DATETIME(6) NOT NULL,
 lease_until DATETIME(6) NULL,
 lease_token CHAR(36) NULL,
 last_error VARCHAR(64) NULL,
 last_finished_at DATETIME(6) NULL,
 KEY ix_maintenance_due(next_at)
) ENGINE=InnoDB;
INSERT IGNORE INTO maintenance_cursor(kind,next_at) VALUES
 ('article',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6))),
 ('memory',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6))),
 ('article_orphan',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6))),
 ('chunk_orphan',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6))),
 ('memory_orphan',TIMESTAMPADD(MINUTE,5,UTC_TIMESTAMP(6)));
CREATE INDEX ix_reading_cleanup ON reading_session(last_heartbeat);
