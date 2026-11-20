-- Space decorations are designer-made artworks only. Remove the preset palette and style system.
DELETE FROM user_space_skin WHERE skin_id NOT IN (SELECT skin_id FROM space_product_artwork);
DELETE FROM space_skin WHERE skin_id NOT IN (SELECT skin_id FROM space_product_artwork);
ALTER TABLE space_skin DROP COLUMN palette_json, DROP COLUMN dress_json, DROP COLUMN part_id;
ALTER TABLE user_info DROP COLUMN space_skin_id, DROP COLUMN space_dress_override;
DROP TABLE IF EXISTS space_dress_part;
