CREATE TABLE IF NOT EXISTS space_artwork (
    artwork_id VARCHAR(32) NOT NULL PRIMARY KEY,
    slot VARCHAR(20) NOT NULL,
    name VARCHAR(60) NOT NULL,
    artist VARCHAR(60) NOT NULL,
    asset_url VARCHAR(512) NOT NULL,
    UNIQUE KEY uq_artwork_slot (artwork_id, slot)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS space_product_artwork (
    skin_id VARCHAR(32) NOT NULL,
    slot VARCHAR(20) NOT NULL,
    artwork_id VARCHAR(32) NOT NULL,
    standalone BOOLEAN NOT NULL,
    single_artwork_id VARCHAR(32) GENERATED ALWAYS AS (IF(standalone, artwork_id, NULL)) STORED,
    PRIMARY KEY (skin_id, slot),
    UNIQUE KEY uq_standalone_artwork (single_artwork_id),
    FOREIGN KEY (skin_id) REFERENCES space_skin(skin_id),
    FOREIGN KEY (artwork_id, slot) REFERENCES space_artwork(artwork_id, slot)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS user_equipped_artwork (
    user_id BIGINT NOT NULL,
    slot VARCHAR(20) NOT NULL,
    artwork_id VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, slot),
    FOREIGN KEY (user_id) REFERENCES user_info(user_id) ON DELETE CASCADE,
    FOREIGN KEY (artwork_id, slot) REFERENCES space_artwork(artwork_id, slot)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
