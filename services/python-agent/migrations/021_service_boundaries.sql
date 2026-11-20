CREATE TABLE IF NOT EXISTS article_agent_save_receipt (
  run_id CHAR(36) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  article_id BIGINT NOT NULL,
  draft_hash CHAR(64) NOT NULL,
  completed TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_article_save_user(user_id,created_at)
);
ALTER TABLE agent_run ADD COLUMN data_source VARCHAR(16) NOT NULL DEFAULT 'business';
UPDATE agent_run r JOIN user_info u ON u.user_id=r.user_id SET r.data_source=u.data_source;
CREATE TABLE IF NOT EXISTS agent_admin_audit (
  command_id CHAR(36) PRIMARY KEY,
  actor_id BIGINT NOT NULL,
  kind VARCHAR(32) NOT NULL,
  target VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
