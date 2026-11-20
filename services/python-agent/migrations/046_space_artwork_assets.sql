-- An artwork carries the images and settings its slot contract asks for (contracts/decoration-slots.json).
ALTER TABLE space_artwork ADD COLUMN assets JSON NULL;
ALTER TABLE space_artwork ADD COLUMN settings JSON NULL;
UPDATE space_artwork SET assets = JSON_OBJECT('images', JSON_OBJECT('image', asset_url), 'items', JSON_ARRAY()) WHERE assets IS NULL;
ALTER TABLE space_artwork MODIFY COLUMN assets JSON NOT NULL;
ALTER TABLE space_artwork DROP COLUMN asset_url;
