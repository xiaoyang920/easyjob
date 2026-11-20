ALTER TABLE space_skin ADD COLUMN palette_json JSON NULL;

UPDATE space_skin SET palette_json =
    '{"day":{"surface":"#f4fbec","accent":"#3e674b","soft":"#e4f2db","selected":"#bfe7a5","bannerStart":"#c5dda3","bannerEnd":"#67968d"},"night":{"surface":"#262f27","accent":"#b7dca8","soft":"#344738","selected":"#bfe7a5","bannerStart":"#485d3b","bannerEnd":"#32575b"}}'
WHERE skin_id = 'forest' AND palette_json IS NULL;

UPDATE space_skin SET palette_json =
    '{"day":{"surface":"#faf5ff","accent":"#6442a2","soft":"#ebe1ff","selected":"#d8c7ff","bannerStart":"#e6bacd","bannerEnd":"#9184d1"},"night":{"surface":"#302838","accent":"#d7c0ff","soft":"#48385e","selected":"#d8c7ff","bannerStart":"#684668","bannerEnd":"#49427b"}}'
WHERE skin_id = 'violet' AND palette_json IS NULL;

UPDATE space_skin SET palette_json =
    '{"day":{"surface":"#fff5ec","accent":"#99402d","soft":"#fbe4d8","selected":"#ffcab1","bannerStart":"#f6c17b","bannerEnd":"#da8c9a"},"night":{"surface":"#342721","accent":"#ffbea4","soft":"#543830","selected":"#ffcab1","bannerStart":"#7a4f31","bannerEnd":"#743d55"}}'
WHERE skin_id = 'sunset' AND palette_json IS NULL;

CREATE TABLE IF NOT EXISTS space_banner_review (
    user_id BIGINT NOT NULL PRIMARY KEY,
    review_id CHAR(36) NOT NULL UNIQUE,
    state VARCHAR(12) NOT NULL,
    position TINYINT UNSIGNED NOT NULL DEFAULT 50,
    image MEDIUMBLOB NULL,
    reason VARCHAR(300) NULL,
    reviewer_id BIGINT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    reviewed_at DATETIME(3) NULL,
    INDEX ix_space_banner_review_queue (state, created_at, user_id)
);
