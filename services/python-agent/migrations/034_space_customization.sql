CREATE TABLE IF NOT EXISTS space_skin (
    skin_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    coin_price INT NOT NULL,
    listed BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    CHECK (coin_price >= 0)
);

CREATE TABLE IF NOT EXISTS user_space_skin (
    user_id BIGINT NOT NULL,
    skin_id VARCHAR(32) NOT NULL,
    request_id CHAR(36) NOT NULL,
    purchase_id CHAR(36) NOT NULL,
    paid_coins INT NOT NULL,
    acquired_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (user_id, skin_id),
    UNIQUE KEY uq_space_skin_request (user_id, request_id),
    CHECK (paid_coins > 0)
);

INSERT IGNORE INTO space_skin(skin_id, name, coin_price, sort_order) VALUES
    ('default', '经典纸面', 0, 0),
    ('forest', '苔绿书房', 20, 10),
    ('violet', '鸢尾暮色', 30, 20),
    ('sunset', '晚霞邮局', 40, 30);

ALTER TABLE user_info ADD COLUMN space_skin_id VARCHAR(32) NOT NULL DEFAULT 'default';
ALTER TABLE user_info ADD COLUMN space_banner_url VARCHAR(512) NULL;
ALTER TABLE user_info ADD COLUMN space_banner_position TINYINT UNSIGNED NOT NULL DEFAULT 50;
