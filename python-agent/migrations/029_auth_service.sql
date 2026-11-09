CREATE TABLE IF NOT EXISTS auth_audit (
  command_id CHAR(36) PRIMARY KEY,
  actor_id BIGINT NOT NULL,
  target_id BIGINT NOT NULL,
  action VARCHAR(48) NOT NULL,
  details VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL,
  INDEX ix_auth_audit_target (target_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE agent_run ADD COLUMN auth_sid CHAR(64) NULL;
ALTER TABLE agent_run ADD COLUMN auth_version BIGINT NULL;
CREATE TABLE IF NOT EXISTS auth_outbox (
  event_id CHAR(36) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  sid CHAR(64) NULL,
  auth_version BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL,
  next_attempt_at DATETIME(6) NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  published_at DATETIME(6) NULL,
  lease_token CHAR(36) NULL,
  lease_until DATETIME(6) NULL,
  INDEX ix_auth_outbox_due (published_at,next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
