ALTER TABLE user_info ADD COLUMN auth_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE admin_operation_log ADD COLUMN reason VARCHAR(300) NULL;
ALTER TABLE admin_operation_log ADD COLUMN details_json JSON NULL;
