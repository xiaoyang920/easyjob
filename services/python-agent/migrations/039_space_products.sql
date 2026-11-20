CREATE TABLE IF NOT EXISTS space_dress_part (
    part_id VARCHAR(32) COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
    part_type VARCHAR(20) NOT NULL,
    name VARCHAR(80) NOT NULL,
    preset VARCHAR(24) NOT NULL,
    style_json JSON NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT IGNORE INTO space_dress_part (part_id, part_type, name, preset) VALUES
    ('wreath', 'avatarFrame', '双环', 'wreath'),
    ('orbit', 'avatarFrame', '星环', 'orbit'),
    ('stamp', 'avatarFrame', '邮票', 'stamp'),
    ('binding', 'cardStyle', '书脊', 'binding'),
    ('floating', 'cardStyle', '悬浮', 'floating'),
    ('postcard', 'cardStyle', '明信片', 'postcard'),
    ('library', 'iconPack', '藏书', 'library'),
    ('celestial', 'iconPack', '星图', 'celestial'),
    ('postal', 'iconPack', '邮局', 'postal'),
    ('arches', 'bannerPattern', '拱形', 'arches'),
    ('stars', 'bannerPattern', '繁星', 'stars'),
    ('postmark', 'bannerPattern', '邮戳', 'postmark');

ALTER TABLE space_skin ADD COLUMN part_id VARCHAR(32) COLLATE utf8mb4_bin NULL;
CREATE UNIQUE INDEX uq_space_product_part ON space_skin(part_id);
ALTER TABLE space_skin ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 0;

INSERT IGNORE INTO space_skin (skin_id, name, coin_price, listed, sort_order, part_id) VALUES
    ('single-wreath', '双环头像框', 8, TRUE, 110, 'wreath'),
    ('single-orbit', '星环头像框', 12, TRUE, 111, 'orbit'),
    ('single-stamp', '邮票头像框', 16, TRUE, 112, 'stamp'),
    ('single-binding', '书脊卡片', 7, TRUE, 120, 'binding'),
    ('single-floating', '悬浮卡片', 10, TRUE, 121, 'floating'),
    ('single-postcard', '明信片卡片', 14, TRUE, 122, 'postcard'),
    ('single-library', '藏书图标', 7, TRUE, 130, 'library'),
    ('single-celestial', '星图图标', 10, TRUE, 131, 'celestial'),
    ('single-postal', '邮局图标', 14, TRUE, 132, 'postal'),
    ('single-arches', '拱形头图纹样', 5, TRUE, 140, 'arches'),
    ('single-stars', '繁星头图纹样', 8, TRUE, 141, 'stars'),
    ('single-postmark', '邮戳头图纹样', 10, TRUE, 142, 'postmark');
