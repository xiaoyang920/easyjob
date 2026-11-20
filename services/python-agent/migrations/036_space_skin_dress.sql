ALTER TABLE space_skin ADD COLUMN dress_json JSON NULL;

UPDATE space_skin
SET dress_json = JSON_OBJECT('cardStyle', 'binding', 'avatarFrame', 'wreath', 'iconPack', 'library', 'bannerPattern', 'arches')
WHERE skin_id = 'forest' AND dress_json IS NULL;

UPDATE space_skin
SET dress_json = JSON_OBJECT('cardStyle', 'floating', 'avatarFrame', 'orbit', 'iconPack', 'celestial', 'bannerPattern', 'stars')
WHERE skin_id = 'violet' AND dress_json IS NULL;

UPDATE space_skin
SET dress_json = JSON_OBJECT('cardStyle', 'postcard', 'avatarFrame', 'stamp', 'iconPack', 'postal', 'bannerPattern', 'postmark')
WHERE skin_id = 'sunset' AND dress_json IS NULL;
