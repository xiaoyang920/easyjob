CREATE TABLE IF NOT EXISTS user_contact_setting (
  owner_id BIGINT NOT NULL, target_id BIGINT NOT NULL, remark VARCHAR(200) NOT NULL DEFAULT '',
  PRIMARY KEY(owner_id,target_id)
);
CREATE TABLE IF NOT EXISTS user_block (
  user_id BIGINT NOT NULL, blocked_user_id BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY(user_id,blocked_user_id), KEY ix_block_target(blocked_user_id,user_id)
);
CREATE TABLE IF NOT EXISTS user_social_setting (
  user_id BIGINT NOT NULL, allow_message_requests TINYINT NOT NULL DEFAULT 1,
  PRIMARY KEY(user_id)
);
CREATE TABLE IF NOT EXISTS direct_chat_state (
  user_low_id BIGINT NOT NULL, user_high_id BIGINT NOT NULL, conversation_id BIGINT NULL,
  state VARCHAR(16) NOT NULL DEFAULT 'NONE', initiator_id BIGINT NULL,
  permission_source VARCHAR(20) NULL, requested_by BIGINT NULL, requested_at DATETIME(6) NULL,
  handled_at DATETIME(6) NULL, viewed_at DATETIME(6) NULL,
  PRIMARY KEY(user_low_id,user_high_id), UNIQUE KEY uq_direct_conversation(conversation_id),
  KEY ix_request_sender(requested_by,requested_at)
);
CREATE TABLE IF NOT EXISTS direct_chat_alias (
  old_conversation_id BIGINT NOT NULL, conversation_id BIGINT NOT NULL,
  PRIMARY KEY(old_conversation_id), KEY ix_alias_canonical(conversation_id)
);
CREATE TABLE IF NOT EXISTS social_migration_state (
  version VARCHAR(64) NOT NULL, completed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY(version)
);
