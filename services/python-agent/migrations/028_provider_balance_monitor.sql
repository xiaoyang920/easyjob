CREATE TABLE IF NOT EXISTS provider_balance_monitor (
    monitor_key VARCHAR(64) NOT NULL PRIMARY KEY,
    currency CHAR(3) NOT NULL,
    account_fingerprint CHAR(64) NOT NULL,
    threshold_amount DECIMAL(20,8) NOT NULL,
    recipient VARCHAR(254) NOT NULL,
    alert_state VARCHAR(16) NOT NULL DEFAULT 'unknown',
    balance_amount DECIMAL(20,8) NULL,
    is_available TINYINT NULL,
    last_checked_at DATETIME(6) NULL,
    check_count BIGINT NOT NULL DEFAULT 0,
    alert_id CHAR(36) NULL,
    alert_sent_at DATETIME(6) NULL,
    last_notified_at DATETIME(6) NULL,
    failure_count INT NOT NULL DEFAULT 0,
    last_error_code VARCHAR(64) NULL,
    next_check_at DATETIME(6) NOT NULL,
    lease_token CHAR(36) NULL,
    lease_until DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
;
