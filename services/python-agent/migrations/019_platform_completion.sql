CREATE TABLE IF NOT EXISTS admin_role_permission (
 role_id INT NOT NULL, permission VARCHAR(40) NOT NULL,
 PRIMARY KEY(role_id,permission)
);
INSERT IGNORE INTO admin_role_permission(role_id,permission) VALUES
 (3,'overview.read'),(3,'articles.read'),(3,'articles.manage'),(3,'reviews.read'),(3,'reviews.manage'),(3,'logs.read'),
 (4,'overview.read'),(4,'statistics.read'),(4,'categories.read'),(4,'categories.manage'),(4,'operations.read'),(4,'operations.manage'),(4,'metrics.read'),(4,'logs.read');
CREATE TABLE IF NOT EXISTS recommendation_feedback (
 user_id BIGINT NOT NULL, article_id BIGINT NOT NULL, target_author_id BIGINT NOT NULL,
 kind VARCHAR(20) NOT NULL,
 created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
 PRIMARY KEY(user_id,article_id), KEY ix_feedback_user_kind(user_id,kind)
);
