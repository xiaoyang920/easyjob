CREATE TABLE IF NOT EXISTS admin_operation_log (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 admin_user_id BIGINT NOT NULL,
 action VARCHAR(32) NOT NULL,
 target_type VARCHAR(24) NOT NULL,
 target_id BIGINT NOT NULL,
 before_value VARCHAR(128) NOT NULL,
 after_value VARCHAR(128) NOT NULL,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 INDEX ix_admin_log_time(created_at,id)
);
