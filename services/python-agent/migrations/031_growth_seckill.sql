ALTER TABLE user_reading_progress ADD COLUMN purchased_millis BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS growth_activity (
 activity_id CHAR(36) PRIMARY KEY, title VARCHAR(80) NOT NULL,
 coin_price INT NOT NULL, growth_seconds INT NOT NULL, total_stock INT NOT NULL, available_stock INT NOT NULL,
 starts_at DATETIME(3) NOT NULL, ends_at DATETIME(3) NOT NULL, pay_seconds INT NOT NULL DEFAULT 120,
 state VARCHAR(16) NOT NULL DEFAULT 'DRAFT', created_by BIGINT NOT NULL,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), INDEX ix_growth_activity(state,ends_at),
 CHECK (available_stock>=0 AND available_stock<=total_stock), CHECK (coin_price>0 AND growth_seconds>0)
);
CREATE TABLE IF NOT EXISTS growth_order (
 order_id CHAR(36) PRIMARY KEY, activity_id CHAR(36) NOT NULL, user_id BIGINT NOT NULL, request_id CHAR(36) NOT NULL,
 coin_cost INT NOT NULL, growth_seconds INT NOT NULL, state VARCHAR(16) NOT NULL,
 expires_at DATETIME(3) NOT NULL, paid_at DATETIME(3) NULL, reason VARCHAR(80) NOT NULL DEFAULT '',
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 UNIQUE KEY uq_growth_buyer(activity_id,user_id), UNIQUE KEY uq_growth_request(activity_id,user_id,request_id),
 INDEX ix_growth_expiry(state,expires_at), INDEX ix_growth_user(user_id,created_at)
);
CREATE TABLE IF NOT EXISTS coin_ledger (
 ledger_id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT NOT NULL, order_id CHAR(36) NOT NULL,
 business_type VARCHAR(24) NOT NULL, delta INT NOT NULL, created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 UNIQUE KEY uq_coin_order(order_id,business_type), INDEX ix_coin_owner(user_id,ledger_id)
);
CREATE TABLE IF NOT EXISTS growth_ledger (
 ledger_id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT NOT NULL, order_id CHAR(36) NOT NULL,
 business_type VARCHAR(24) NOT NULL, delta_millis BIGINT NOT NULL, created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 UNIQUE KEY uq_growth_credit(order_id,business_type), INDEX ix_growth_owner(user_id,ledger_id)
);
CREATE TABLE IF NOT EXISTS growth_outbox (
 event_id CHAR(36) PRIMARY KEY, activity_id CHAR(36) NOT NULL, order_id CHAR(36) NOT NULL,
 event_type VARCHAR(24) NOT NULL, delivered TINYINT NOT NULL DEFAULT 0, attempts INT NOT NULL DEFAULT 0,
 next_attempt_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), last_error VARCHAR(80) NOT NULL DEFAULT '',
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 UNIQUE KEY uq_growth_effect(order_id,event_type), INDEX ix_growth_outbox(delivered,next_attempt_at)
);
